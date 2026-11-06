from django.db.models import OuterRef, Subquery
from django.db.models.functions import Coalesce
from django.utils.translation import gettext_lazy as _

from core import audit
from core.crud import Mount, Resource, tab_fields
from farm.stock.dates import site_today

from .. import read, scope, services, units
from ..forms import EmployeeForm
from ..forms.employee import PLACEMENT_FIELDS
from ..models import Employee, EmploymentType, Posting

STATUSES = [('current', _('Working here')), ('left', _('Left'))]


class EmployeeResource(Resource):
    """The Team list. A person reaches only the people of their own team (hr.scope.team) unless they hold Everyone:
    the rule is `scoped`, so the list, a person's page, their edit and the placement they are given are all of the
    team, whatever the address. Read gives the read page; only Create and Edit give the form. There is no delete: a
    person who leaves gets a last day."""

    model = Employee
    form_class = EmployeeForm
    name, plural = _('employee'), _('employees')
    url_prefix = 'hr/team'
    mounts = (Mount(scope.PRODUCTION, 'production/team/people'),)
    actions = ('add', 'change')
    search_fields = ['employee_number', 'first_name', 'last_name', 'user__username', 'user__first_name',
                     'user__last_name']
    list_template = 'hr/employee_list.html'
    detail_template = 'hr/employee_detail.html'
    page_size = 50
    icon = 'users'

    @classmethod
    def queryset(cls):
        return super().queryset().select_related('user')

    @classmethod
    def scoped(cls, request, objects):
        return objects.filter(pk__in=scope.team(request.user, realm=scope.realm_for(request)).values('pk'))

    @classmethod
    def allowed(cls, request, employee, action):
        """One's own record is edited by a holder of Everyone only (hr.services.own_record)."""
        return not services.own_record(request.user, employee)

    @classmethod
    def form(cls, request, *args, **kwargs):
        return cls.form_class(*args, editor=request.user, realm=scope.realm_for(request), **kwargs)

    @classmethod
    def list_queryset(cls, request):
        """The team with each person's placement today read in the same query (a subquery, not one per row)."""
        today = site_today(None)
        placement = Posting.objects.filter(scope.covering(today), employee=OuterRef('pk'))
        return cls.queryset().annotate(
            department_name=Coalesce(Subquery(placement.values('production_department__name')[:1]),
                                     Subquery(placement.values('office_department__name')[:1])),
            current_title=Subquery(placement.values('title')[:1]))

    @classmethod
    def filter_list(cls, request, objects):
        chosen_type, chosen_status = request.GET.get('type', ''), request.GET.get('status', '')
        department = units.find(request.GET.get('department', ''))
        if chosen_type in EmploymentType.values:
            objects = objects.filter(employment_type=chosen_type)
        else:
            chosen_type = ''
        today = site_today(None)
        if chosen_status == 'current':
            objects = objects.filter(left_on__isnull=True) | objects.filter(left_on__gte=today)
        elif chosen_status == 'left':
            objects = objects.filter(left_on__lt=today)
        else:
            chosen_status = ''
        if department is not None:
            members = Posting.objects.filter(scope.covering(today), **{units.field_of(department): department})
            objects = objects.filter(pk__in=members.values('employee'))
        return objects.order_by(*Employee._meta.ordering), {
            'types': EmploymentType.choices, 'chosen_type': chosen_type, 'statuses': STATUSES,
            'chosen_status': chosen_status, 'departments': units.choices(kinds=[scope.realm_for(request)]),
            'chosen_department': units.token(department),
            'today': today, 'own': next((employee.pk for employee in Employee.objects.filter(user=request.user)
                                         if services.own_record(request.user, employee)), None),
        }

    @classmethod
    def snapshot(cls, employee):
        """The person's own columns; where they work is logged as placements (hr.services)."""
        fields = [name for name in tab_fields(EmployeeForm.tabs) if name not in PLACEMENT_FIELDS]
        return audit.snapshot(employee, fields, getattr(EmployeeForm.Meta, 'labels', {}))

    @classmethod
    def after_save(cls, request, employee, created):
        """The placement the form asked for, and the placements agreeing with a last day, in the same transaction."""
        placement = getattr(employee, 'placement', None)
        if placement is not None:
            department, title, day = placement
            services.move(request.user, employee, department, title, day)
        services.align_placements(request.user, employee)

    @classmethod
    def detail_extras(cls, request, employee):
        return {'placements': employee.postings.select_related('production_department', 'office_department'),
                'today': site_today(None)}

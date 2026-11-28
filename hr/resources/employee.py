from django.db.models import OuterRef, Subquery
from django.db.models.functions import Coalesce
from django.utils import formats
from django.utils.translation import gettext_lazy as _

from core import listprops
from core.crud import Mount, Resource
from farm.stock.dates import site_today

from .. import scope, services, units
from ..forms import EmployeeForm
from ..models import Employee, EmploymentType, Posting

STATUSES = [('current', _('Working here')), ('left', _('Left'))]


class EmployeeResource(Resource):
    """The Team list. A person reaches only the people of their own team (hr.scope.team) unless they hold Everyone:
    the rule is `scoped`, so the list, a person's page, their edit and the placement they are given are all of the
    team, whatever the address. Read gives the read page; only Create and Edit give the form. There is no delete: a
    person who leaves gets a last day. Every write is hr.services' (add_employee, change_employee, which hands a last day
    to leave_company and a placement to move): the tab reads the form and hands it over."""

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
    service_writes = True

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
    def create_record(cls, request, form):
        return services.add_employee(request.user, form.values(), form.placement)

    @classmethod
    def change_record(cls, request, form, current):
        return services.change_employee(request.user, current, form.values(), form.placement)

    @classmethod
    def detail_extras(cls, request, employee):
        return {'placements': employee.postings.select_related('production_department', 'office_department'),
                'today': site_today(None)}

    # --- the list in the new look (core/listprops.py), the words of hr/employee_list.html ---------------------------
    search_placeholder = _('Search by name or number')
    empty_text = _('The people of your team appear here. Someone who manages a department sees the people placed in it.')

    @classmethod
    def list_filters(cls, view, context):
        return [
            listprops.choice('department', _('Department'), context['chosen_department'], [('', _('All departments'))],
                             groups=context['departments']),
            listprops.choice('type', _('Employment type'), context['chosen_type'], [('', _('All types')), *context['types']]),
            listprops.choice('status', _('Status'), context['chosen_status'], [('', _('Any status')), *context['statuses']]),
        ]

    @classmethod
    def list_rows(cls, view, objects, context):
        L, today, own = listprops, context['today'], context['own']
        rows = []
        for employee in objects:
            name = employee.full_name
            show = view.url('detail', employee.pk)
            editable = context['can_change'] and employee.pk != own
            edit = view.url('edit', employee.pk) if editable else None
            left = employee.left_on is not None and employee.left_on < today
            rows.append(L.row(employee.pk, {
                'employee': L.cell(name, href=edit or show, strong=True, sub=[employee.employee_number]),
                'type': L.cell(employee.get_employment_type_display()),
                'department': L.cell(employee.department_name) if employee.department_name
                else L.cell(chip=L.chip('warning', _('Not placed'))),
                'title': L.cell(employee.current_title or '–'),
                'joined': L.cell(formats.date_format(employee.joined_on, 'DATE_FORMAT')),
                'status': L.cell(chip=L.chip('neutral', f"{_('Left')} {formats.date_format(employee.left_on, 'DATE_FORMAT')}")
                                 if left else L.chip('ok', _('Working here'))),
            }, actions=[L.link(show, _('Show %(name)s') % {'name': name}, 'search'),
                        *([L.link(edit, _('Edit %(name)s') % {'name': name}, 'pencil')] if edit else [])]))
        return {'columns': [L.column('employee', _('Employee')), L.column('type', _('Type')),
                            L.column('department', _('Department')), L.column('title', _('Title')),
                            L.column('joined', _('Joined')), L.column('status', _('Status'))],
                'rows': rows}

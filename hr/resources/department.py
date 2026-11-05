from django.utils.translation import gettext_lazy as _

from core.crud import Resource

from .. import read
from ..forms import OfficeDepartmentForm
from ..models import OfficeDepartment

KINDS = [(read.PRODUCTION, _('Production')), (read.OFFICE, _('Office'))]
STATUSES = [('active', _('Active')), ('inactive', _('Inactive'))]


class OfficeDepartmentResource(Resource):
    """The Departments page. Its list is one read over two kinds: the farm's production departments (never copied,
    edited on their own page under Production) and HR's office departments, which this tab creates, edits and
    deletes. So the list, its search and its filters are written here (the default ones narrow a queryset)."""

    model = OfficeDepartment
    form_class = OfficeDepartmentForm
    name, plural = _('office department'), _('office departments')
    url_prefix = 'hr/departments'
    list_template = 'hr/department_list.html'
    icon = 'layout-grid'

    @classmethod
    def queryset(cls):
        return super().queryset().select_related('site', 'manager', 'parent')

    @classmethod
    def list_queryset(cls, request):
        return read.departments(request.user)

    @classmethod
    def search(cls, objects, query):
        needle = query.casefold()
        return [row for row in objects if needle in row.name.casefold() or needle in row.code.casefold()]

    @classmethod
    def filter_list(cls, request, objects):
        kind, status = request.GET.get('kind', ''), request.GET.get('status', '')
        if kind in dict(KINDS):
            objects = [row for row in objects if row.kind == kind]
        else:
            kind = ''
        if status in dict(STATUSES):
            objects = [row for row in objects if row.status == status]
        else:
            status = ''
        return objects, {'kinds': KINDS, 'chosen_kind': kind, 'statuses': STATUSES, 'chosen_status': status,
                         'production': read.PRODUCTION}

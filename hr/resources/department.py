from django.utils.translation import gettext_lazy as _

from core.crud import Resource

from .. import read
from ..forms import OfficeDepartmentForm
from ..models import OfficeDepartment

STATUSES = [('active', _('Active')), ('inactive', _('Inactive'))]


class OfficeDepartmentResource(Resource):
    """The Departments page of Company › HR: the office departments, which this tab creates, edits and deletes, in tree
    order with the head count the viewer may see (hr.read.departments). The production departments are the farm's own rows,
    under Production. The list is a read in tree order, so its search and filter are written here (the default ones narrow
    a queryset)."""

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
        status = request.GET.get('status', '')
        if status in dict(STATUSES):
            objects = [row for row in objects if row.status == status]
        else:
            status = ''
        return objects, {'statuses': STATUSES, 'chosen_status': status}

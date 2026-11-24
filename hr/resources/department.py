from django.utils.translation import gettext_lazy as _

from core import listprops as L
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

    search_placeholder = _('Search by name or code')
    empty_text = _('The office departments of the company, such as Finance. The production departments are under Production.')

    @classmethod
    def list_filters(cls, view, context):
        return [L.choice('status', _('Status'), context['chosen_status'], [('', _('Any status')), *context['statuses']])]

    @classmethod
    def list_rows(cls, view, objects, context):
        def manager(row):
            if row.manager is None:
                return L.cell(chip=L.chip('warning', _('No manager')))
            return L.cell(row.manager.get_full_name() or row.manager.get_username())
        return {'columns': [L.column('department', _('Department')), L.column('status', _('Status')),
                            L.column('site', _('Site')), L.column('manager', _('Manager')),
                            L.column('people', _('People'), numeric=True)],
                'rows': [L.row(row.pk, {
                    # the code and the parent in one line, as the classic page says them
                    'department': L.title(view, context, row, row.name, sub=[
                        ' · '.join([row.code, *([_('in %(name)s') % {'name': row.parent.name}] if row.parent else [])])]),
                    'status': L.cell(chip=L.chip('ok', _('Active')) if row.status == 'active' else L.chip('neutral', _('Inactive'))),
                    'site': L.cell(row.site.name) if row.site else L.cell(chip=L.chip('warning', _('No site'))),
                    'manager': manager(row),
                    'people': L.cell(row.head_count),
                }, L.edit_delete(view, context, row, row.name)) for row in objects]}

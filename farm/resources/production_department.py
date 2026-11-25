from django.template.defaultfilters import floatformat
from django.utils.http import urlencode
from django.utils.translation import gettext_lazy as _, ngettext

from core import listprops as L
from core.crud import NONE, Resource, filter_by

from ..forms import ProductionDepartmentForm
from ..models import ProductionDepartment, Site


class ProductionDepartmentResource(Resource):
    model = ProductionDepartment
    form_class = ProductionDepartmentForm
    name, plural = _('production department'), _('production departments')
    url_prefix = 'production-departments'
    search_fields = ['name', 'code']
    list_template = 'farm/production_department_list.html'
    icon = 'layout-grid'

    @classmethod
    def form(cls, request, *args, **kwargs):
        return cls.form_class(*args, editor=request.user, **kwargs)

    @classmethod
    def queryset(cls):
        return super().queryset().select_related('site', 'manager')

    @classmethod
    def filter_list(cls, request, objects):
        sites = Site.objects.all()
        objects, chosen = filter_by(request, objects, 'site', sites, 'site_id', allow_none=True)
        return objects, {
            'sites': sites, 'chosen_site': chosen, 'none_value': NONE,
            'without_site': ProductionDepartment.objects.filter(site__isnull=True).count(),
        }

    # The list in the new look (core/listprops.py), in the classic list's words (farm/production_department_list.html).
    search_placeholder = _('Search by name or code')
    empty_text = _('Production departments organise a site, e.g. a hatchery hall or a grow-out unit.')

    @classmethod
    def list_filters(cls, view, context):
        return [L.choice('site', _('Site'), context['chosen_site'],
                         [('', _('All sites')), (context['none_value'], _('Without a site')),
                          *((site.pk, site.name) for site in context['sites'])])]

    @classmethod
    def list_rows(cls, view, objects, context):
        notices = []
        if context['without_site']:
            count = context['without_site']
            notices.append(L.notice('without-site', 'warning', ngettext(
                '%(count)s production department is not on any site.',
                '%(count)s production departments are not on any site.', count) % {'count': count},
                link=(f"?{urlencode({'site': context['none_value']})}", _('Show them'))))

        def manager(department):
            person = department.manager
            return (person.get_full_name() or person.get_username()) if person else '–'

        return {
            'columns': [L.column('department', _('Production department')), L.column('type', _('Type')),
                        L.column('site', _('Site')), L.column('manager', _('Manager')),
                        L.column('capacity', _('Capacity'), numeric=True)],
            'notices': notices,
            'rows': [L.row(department.pk, {
                'department': L.title(view, context, department, department.name, sub=[department.code]),
                'type': L.cell(department.get_type_display()),
                'site': L.cell(department.site.name) if department.site
                else L.cell(chip=L.chip('warning', _('No site'))),
                'manager': L.cell(manager(department)),
                'capacity': L.cell('–' if department.capacity is None else floatformat(department.capacity, '-2g')),
            }, L.edit_delete(view, context, department, department.name)) for department in objects],
        }

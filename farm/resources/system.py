from django.template.defaultfilters import floatformat
from django.urls import reverse
from django.utils.http import urlencode
from django.utils.translation import gettext_lazy as _, ngettext

from core import listprops as L
from core.crud import NONE, Resource, filter_by

from ..forms import SystemForm
from ..models import ProductionDepartment, Site, System
from ..water import points

def _nested(system):
    """A system's name as the classic list nests it: under its parent a "↳" (an em space more per level deeper)."""
    depth = min(getattr(system, 'depth', 0) or 0, 5)
    return f"{chr(0x2003) * (depth - 1)}↳ {system.name}" if depth else system.name


# a system's status as its chip in the new look (the classic badge's colour: operational green, the others not)
SYSTEM_CHIP = {'operational': 'ok', 'maintenance': 'warning', 'offline': 'neutral', 'construction': 'neutral'}


class SystemResource(Resource):
    model = System
    form_class = SystemForm
    name, plural = _('system'), _('systems')
    url_prefix = 'systems'
    search_fields = ['name', 'code']
    list_template = 'farm/system_list.html'
    icon = 'waves'

    @classmethod
    def queryset(cls):
        return super().queryset().select_related('site', 'production_department', 'parent')

    @classmethod
    def after_save(cls, request, system, created):
        """A new system starts with its loop point (farm/water/points.py), logged with it."""
        if created:
            points.create_defaults(request.user, system)

    @classmethod
    def filter_list(cls, request, objects):
        sites, departments = Site.objects.all(), ProductionDepartment.objects.all()
        objects, chosen_site = filter_by(request, objects, 'site', sites, 'site_id')
        objects, chosen_department = filter_by(
            request, objects, 'production_department', departments, 'production_department_id', allow_none=True)
        return System.in_tree_order(objects), {
            'sites': sites, 'chosen_site': chosen_site,
            'departments': departments, 'chosen_department': chosen_department, 'none_value': NONE,
            'without_department': System.objects.filter(production_department__isnull=True).count(),
        }

    # The list in the new look (core/listprops.py), in the classic list's words (farm/system_list.html), with one action
    # more: the system's water history (System › Water, farm:system_water), for a person who may read the water.
    search_placeholder = _('Search by name or code')
    empty_text = _('A system is a RAS, a pond, a cage line or a hatchery on a site; tanks and equipment belong to it.')

    @classmethod
    def list_filters(cls, view, context):
        return [
            L.choice('site', _('Site'), context['chosen_site'],
                     [('', _('All sites')), *((site.pk, site.name) for site in context['sites'])]),
            L.choice('production_department', _('Production department'), context['chosen_department'],
                     [('', _('All production departments')), (context['none_value'], _('Without a production department')),
                      *((department.pk, department.name) for department in context['departments'])]),
        ]

    @classmethod
    def list_rows(cls, view, objects, context):
        user = view.request.user

        def figure(value):
            return L.cell('–' if value is None else floatformat(value, '-2g'))

        def units(system):
            if system.units and user.has_perm('farm.view_tank'):
                return L.cell(system.units, href=f"{reverse('farm:tank_list')}?{urlencode({'system': system.pk})}")
            return L.cell(system.units)

        def actions(system):
            done = []
            if user.has_perm('farm.view_samplingpoint'):
                done.append(L.link(f"{reverse('farm:samplingpoint_list')}?{urlencode({'system': system.pk})}",
                                   _('Sampling points of %(name)s') % {'name': system.name}, 'droplet'))
            if user.has_perm('farm.view_watermeasurement'):
                done.append(L.link(reverse('farm:system_water', args=[system.pk]),
                                   _('Water of %(name)s') % {'name': system.name}, 'chart-line'))
            return done + L.edit_delete(view, context, system, system.name)

        notices = []
        if context['without_department']:
            count = context['without_department']
            notices.append(L.notice('without-department', 'warning', ngettext(
                '%(count)s system is not in any production department.',
                '%(count)s systems are not in any production department.', count) % {'count': count},
                link=(f"?{urlencode({'production_department': context['none_value']})}", _('Show them'))))
        return {
            'columns': [L.column('system', _('System')), L.column('type', _('Type')), L.column('status', _('Status')),
                        L.column('site', _('Site')), L.column('department', _('Production department')),
                        L.column('volume', _('Volume (m³)'), numeric=True),
                        L.column('biomass', _('Max biomass (kg)'), numeric=True),
                        L.column('units', _('Units'), numeric=True)],
            'notices': notices,
            'rows': [L.row(system.pk, {
                # the code and the parent in one line, as the classic page says them; a nested system's depth by "in …"
                'system': L.title(view, context, system, _nested(system), sub=[' · '.join(
                    [system.code, *([_('in %(name)s') % {'name': system.parent.name}] if system.parent else [])])]),
                'type': L.cell(system.get_type_display()),
                'status': L.cell(chip=L.chip(SYSTEM_CHIP.get(system.status, 'neutral'), system.get_status_display())),
                'site': L.cell(system.site.name),
                'department': L.cell(system.production_department.name) if system.production_department
                else L.cell(chip=L.chip('warning', _('No production department'))),
                'volume': figure(system.total_volume_m3),
                'biomass': figure(system.max_biomass_kg),
                'units': units(system),
            }, actions(system)) for system in objects],
        }

"""Operations › Water chemistry's Latest and History in the new look (farm.water.views.water_page behind `?ui=next`): the
table on the shared list page (island `list-page`, frontend/islands/ui/ListPage.tsx, words of core/listprops.py) from the
context the view read for the classic page (templates/farm/water.html), in its words: the same rows, the same values
judged on read (farm/water/read.py), the same filters as one GET form with the same names and values. The tabs, the
alarms' safety line ({% alarm_watch promise=True %}), "How values are judged" and a history's heading are the server's,
as on the classic page (templates/farm/water_next.html).

A value is said as Production units says it (farm.stock.units_next.value_cell): its figure, in its status's chip when it
is critical, a warning, cannot be evaluated or is stale (never drawn as an OK one), what was measured when it is stored
converted, the unit's own older value a status keeps, how it was worked out and why it could not be, and on Latest where
it came from and how old it is. A point's status is its chip in the classic words ("Warning, no recent data")."""
from django.utils import formats
from django.utils.translation import gettext as _, ngettext

from core import listprops as L

from ..stock.units_next import POINT_CHIP, point_said, value_cell
from ..templatetags.water import sample_clock

ALERT_ROWS = ('critical', 'warning')


def _columns(parameters):
    return [L.column(parameter.code, parameter.short, numeric=True) for parameter in parameters]


def _toolbar(label, filters, keep=()):
    return {'label': label, 'search': None, 'keep': [{'name': name, 'value': str(value)} for name, value in keep],
            'filters': filters, 'submit': _('Filter'), 'add': None}


def _sites(context):
    site = context['site']
    return L.choice('site', _('Site'), site.pk if site else '',
                    [('', _('All sites')), *((each.pk, each.name) for each in context['sites'])])


def latest_props(request, context):
    """Latest: a row per point (a unit's middle point, a loop, another point sampled lately), its status and its latest
    values, each with its origin and age; its history (Tank › Water for a unit, the history page for the others)."""
    rows = []
    for at, row in enumerate(context['rows']):
        owner, point, water = row['owner'], row['point'], row['water']
        place = owner.site.name if row['loop'] else ', '.join(
            name for name in (owner.production_department.name,
                              owner.production_department.site.name if owner.production_department.site else '') if name)
        said = point_said(water)
        cells = {
            'point': L.cell(owner.code, href=row['history_url'], strong=True,
                            sub=[f'{point.name} · {point.get_kind_display()}' if point else _('No middle point'), place]),
            'status': L.cell(chip=L.chip(POINT_CHIP.get(water.status, 'neutral'), said),
                             sub=[water.why_no_limit, *water.why_unevaluated, *water.why_silent]),
            **{parameter.code: value_cell(reading, whole=True)
               for parameter, reading in zip(context['columns'], row['cells'])},
        }
        rows.append(L.row(f'{at}-{point.pk if point else owner.pk}', cells,
                          [L.link(row['history_url'], _('History'), 'history')],
                          status=water.status if water.status in ALERT_ROWS else None))
    notices = []
    if context['sensors_failed']:
        notices.append(L.notice('sensors-failed', 'warning', _(
            'The live sensor values could not be read: the values below come from the water samples only.')))
    return {
        'csrfToken': '', 'tabs': None,
        'toolbar': _toolbar(_('Water chemistry'), [_sites(context)]),
        'notices': notices, 'lines': [],
        'table': {'label': _('Latest water values, scrolls sideways'),
                  'columns': [L.column('point', _('Sampling point')), L.column('status', _('Status')),
                              *_columns(context['columns'])],
                  'rows': rows, 'actionsLabel': _('History')},
        'empty': {'title': _('No units yet'), 'text': _(
            'Water is sampled at the sampling points of the tanks, ponds and cages of Setup, of the loops of its systems '
            'and of its equipment.'), 'link': None, 'add': None},
        'pager': None,
    }


def history_props(request, context):
    """History: the samples of the span, newest first, a page at a time, each value judged on read; a voided sample
    struck through with who voided it and why; Void for a person who may."""
    owner, point = context['owner'], context['point']
    filters = [_sites(context), L.choice(
        'owner', _('Unit, system or equipment'), next((value for _label, options in context['owner_groups']
                                                       for value, _text, selected in options if selected), ''),
        [('', _('All units, systems and equipment'))],
        groups=[(label, [(value, text) for value, text, _selected in options]) for label, options in context['owner_groups']])]
    if owner is not None:
        filters.append(L.choice('point', _('Sampling point'), point.pk if point else '',
                                [('', _('All its points')), *((each.pk, f'{each.name} · {each.get_kind_display()}')
                                                              for each in context['point_choices'])]))
    filters += [L.day('from', _('From'), context['start']), L.day('to', _('To'), context['end']),
                L.check('alerts', _('Only warnings and criticals'), context['alerts_only'])]
    rows = []
    for row in context['history']:
        sample = row.sample
        moment = formats.date_format(sample_clock(sample), 'DATETIME_FORMAT')
        voided = [_('voided by %(name)s: %(reason)s') % {
            'reason': sample.void_reason, 'name': sample.deleted_by.get_username() if sample.deleted_by else 'system'}] \
            if sample.is_deleted else []
        cells = {
            'measured': L.cell(moment, sub=voided),
            'point': L.cell(sample.point.owner.code, href=row.history_url, strong=True,
                            sub=[f'{sample.point.name} · {sample.point.get_kind_display()}']),
            'source': L.cell(sample.get_source_display(), sub=[sample.notes]),
            **{parameter.code: value_cell(reading, latest=False, whole=True)
               for parameter, reading in zip(context['columns'], row.cells)},
            'by': L.cell(sample.created_by.get_username() if sample.created_by else 'system'),
        }
        actions = [L.link(row.void_url, _('Void'), 'x', danger=True, labelled=True)] if getattr(row, 'void_url', '') else []
        rows.append(L.row(sample.pk, cells, actions, voided=sample.is_deleted,
                          status=None if sample.is_deleted or row.status not in ALERT_ROWS else row.status))
    notices = []
    if context['clipped']:
        notices.append(L.notice('clipped', 'warning', ngettext(
            'A page shows at most %(days)s day: the first day was moved.',
            'A page shows at most %(days)s days: the first day was moved.', context['span']) % {'days': context['span']}))
    return {
        'csrfToken': '', 'tabs': None,
        'toolbar': _toolbar(_('Water chemistry'), filters, keep=[('view', 'history')]),
        'notices': notices, 'lines': [],
        'table': {'label': _('Water samples, scrolls sideways'),
                  'columns': [L.column('measured', _('Measured at')), L.column('point', _('Sampling point')),
                              L.column('source', _('Source')), *_columns(context['columns']), L.column('by', _('By'))],
                  'rows': rows, 'actionsLabel': _('Actions')},
        'empty': {'title': _('No samples match these filters.'), 'text': _('From %(start)s to %(end)s.') % {
            'start': formats.date_format(context['start'], 'DATE_FORMAT'),
            'end': formats.date_format(context['end'], 'DATE_FORMAT')}, 'link': None, 'add': None},
        'pager': L.pager(context['page'], context['pager_query']),
    }


def page_props(request, context):
    """The list page's props of the tab the view drew (`showing_history`), from its context."""
    return history_props(request, context) if context['showing_history'] else latest_props(request, context)


"""Production › Production units in the new look (farm.stock.views.production_units behind `?ui=next`): the table on the
shared list page (island `list-page`, frontend/islands/ui/ListPage.tsx, words of core/listprops.py) from the rows the view
read for the classic page, worded as templates/farm/production_units.html words them (the same msgids, the same
filters: the classic page's filter buttons are the toolbar's selects with the same values), and beside it the unit's
drawer the server draws as on the classic page (templates/farm/_unit_drawer.html: every section of it, nothing dropped).

A row's code opens the unit's drawer (`?unit=`, the filters kept), its Edit the unit's form (farm:tank_edit, only with
the right to change units; the design opens the drawer for both). A water value is said with its origin and age
(owner rule A1), a warning or critical one in its status chip, a stale one as stale: never as OK."""
from django.urls import reverse
from django.utils import formats
from django.utils.translation import gettext as _

from core import listprops as L
from farm.templatetags.feeding import fcr, fed_on
from farm.templatetags.health import harvest_from
from farm.templatetags.stock import density, fish, grams, join_codes, kilos, percent
from farm.templatetags.water import reading_figure, sample_clock, source, status_label

FCR_SAID = ('Biological feed conversion ratio: the feed given per kg of growth, dead fish credited, from stocking to the '
            'last weighing')
VALUE_CHIP = {'critical': 'critical', 'warning': 'warning', 'stale': 'stale'}
POINT_CHIP = {'critical': 'critical', 'warning': 'warning', 'unevaluated': 'warning', 'ok': 'ok', 'stale': 'stale',
              'not_measured': 'nodata'}


def point_said(water):
    """A point's status in words, as farm/_water_chip.html says it ("Warning, no recent data" when only old values are)."""
    if water.old_alert:
        return _('%(status)s, no recent data') % {'status': status_label(water.status)}
    return str(status_label(water.status))


WAS = {'critical': lambda: _('Stale, was critical'), 'warning': lambda: _('Stale, was warning')}


def was_said(reading):
    """What a stale value that was critical or a warning says beside its figure: the classic title's words (farm/
    _water_value.html: its status and what it was, the moment of its sample, how it was worked out, its provenance and
    note) but its age, which the origin line under it says already, so the line stays short in a narrow column."""
    parts = [WAS[reading.old_alert](), formats.date_format(sample_clock(reading.sample), 'DATETIME_FORMAT')]
    if reading.derived:
        parts.append(_('worked out from the sensors') if reading.sample.live else _('worked out from the sample'))
    parts += [str(each) for each in (reading.provenance, reading.note) if each]
    return ' · '.join(str(part) for part in parts)


def value_cell(reading):
    """One latest water value (farm/_water_face.html): its figure (in its status's chip when it is a warning, critical
    or stale), what was measured when it is stored converted, the unit's own older value a status keeps, and where it
    came from and how old it is. No value is "no data", never a dash. A stale value that was critical or a warning when
    it was taken (Reading.old_alert, F-244) keeps its stale chip and says in words what it was ("Stale, was critical"
    and the sample's moment; its age is the origin line's): never only "stale"."""
    if reading is None:
        return L.cell(_('no data'))
    said = source(reading)
    figure = '?' if reading.value is None else str(reading_figure(reading))
    sub = [reading.measured or '', getattr(reading, 'last_own_said', '') if reading.last_own else '',
           f"{said['origin']} · {said['age']}"]
    if reading.old_alert:
        sub.insert(0, was_said(reading))
    tone = VALUE_CHIP.get(reading.status)
    return L.cell(chip=L.chip(tone, figure), sub=sub) if tone else L.cell(figure, sub=sub)


def unit_cell(row):
    unit, stock = row['unit'], row['stock']
    department = unit.production_department
    # the design's "name · department"; the classic page's "department, site" kept whole in it
    sub = [f'{unit.name} · ' + department.name + (f', {department.site.name}' if department.site else '')]
    chips = []
    if row['water']:
        water = row['water']
        chips.append(L.chip(POINT_CHIP.get(water.status, 'neutral'), point_said(water)))
    for found in (mix_chips(stock.size_mixes if stock else ()), placement_chips(row['placements'])):
        chips += found[0]
        sub += found[1]
    if row['withdrawal']:
        chips.append(L.chip('hold', _('Withdrawal')))
        sub += [f'{block.batch.code}: {harvest_from(block)}' for block in row['withdrawal']]
    return L.cell(unit.code, href=row['href'], strong=True, sub=sub, chips=chips)


def mix_chips(mixes):
    """([chip], [sub-line]) of a unit's size mixes (farm/_size_mixes.html): a warning chip each, its lots on a line."""
    chips, sub = [], []
    for mix in mixes:
        chips.append(L.chip('warning', _('Mixed sizes: %(heavy)s and %(light)s (limit %(limit)s)') % {
            'heavy': mix.heaviest.text, 'light': mix.lightest.text, 'limit': _times(mix.limit)}))
        sub.append(f'{mix.heavy.code} · {mix.light.code}')
    return chips, sub


def placement_chips(placements):
    """([chip], [sub-line]) of a unit's placements (farm/_placements.html): an accent chip each, its title on a line."""
    chips, sub = [], []
    for chip in placements:
        chips.append(L.chip('accent', chip.label))
        if chip.title:
            sub.append(chip.title)
    return chips, sub


def _times(value):
    from farm.templatetags.stock import times
    return times(value)


def batch_cell(row):
    stock = row['stock']
    if stock is None:
        if row['takes_fish']:
            return L.cell(_('Empty — ready to stock'), href=row['href'])
        return L.cell(_('Empty · %(status)s') % {'status': row['unit'].get_status_display()}, href=row['href'])
    sub = []
    if stock.batches:
        species = stock.batches[0].species
        sub.append(species.local_name or species.common_name)
    if stock.cleaner:
        sub.append(_('Cleaner fish: %(batches)s · %(fish)s fish') % {
            'fish': fish(stock.cleaner_stock.count), 'batches': join_codes(stock.cleaner_stock.batches)})
    return L.cell(join_codes(stock.batches) if stock.batches else row['unit'].code, href=row['href'], sub=sub)


def density_cell(stock):
    if stock is None:
        return L.cell('—')
    # the design's: the density, and under it the share of the unit's capacity as a gauge (the classic page's .ui-gauge:
    # the bar and the share in words, so the bar is never the only cue; over capacity also said by its chip)
    share = _('%(percent)s of capacity') % {'percent': percent(stock.capacity)}
    return L.cell(density(stock.density), gauge=L.gauge(stock.capacity, share, 'critical' if stock.over_capacity else None),
                  chips=[L.chip('critical', _('Over'))] if stock.over_capacity else ())


def fcr_cell(feeding):
    conversion = feeding.conversion if feeding else None
    figure = fcr(conversion.biological if conversion else None)
    why = conversion.why_no_biological if feeding and not conversion.biological else ''
    return L.cell(figure, sub=[why])


def fed_cell(feeding):
    if not feeding:
        return L.cell('—')
    return L.cell(fed_on(feeding.last_fed, feeding.today), sub=[
        _('in %(unit)s') % {'unit': feeding.last_fed_in.code} if feeding.last_fed_in else ''])


def units_props(request, context):
    """The list page's props of Production units from the view's `context` (the classic page's)."""
    show_feeding, show_water = context['show_feeding'], context['show_water']
    params = context['params']
    columns = [L.column('unit', _('Unit')), L.column('batch', _('Batch')), L.column('fish', _('Fish'), numeric=True),
               L.column('weight', _('Avg. weight'), numeric=True), L.column('biomass', _('Biomass'), numeric=True),
               L.column('density', _('Density · capacity'))]
    if show_feeding:
        columns.append(L.column('fcr', _('bFCR'), numeric=True))
    columns.append(L.column('survival', _('Survival'), numeric=True))
    if show_water:
        columns += [L.column('temperature', _('Temp. (°C)'), numeric=True), L.column('oxygen', _('O₂ (mg/L)'), numeric=True)]
    if show_feeding:
        columns.append(L.column('fed', _('Last fed')))
    can_edit = request.user.has_perm('farm.change_tank')
    rows = []
    for row in context['rows']:
        unit, stock = row['unit'], row['stock']
        water = row['water']
        cells = {
            'unit': unit_cell(row), 'batch': batch_cell(row),
            'fish': L.cell(fish(stock.count if stock else None)),
            'weight': L.cell(grams(stock.avg_weight_g if stock else None)),
            'biomass': L.cell(kilos(stock.biomass_kg if stock else None)),
            'density': density_cell(stock),
            'survival': L.cell(percent(stock.survival if stock else None, 1)),
        }
        if show_feeding:
            cells['fcr'] = fcr_cell(row['feeding'])
            cells['fed'] = fed_cell(row['feeding'])
        if show_water:
            readings = water.readings if water else {}
            cells['temperature'] = value_cell(readings.get('temperature_c'))
            cells['oxygen'] = value_cell(readings.get('oxygen_mg_l'))
        actions = [L.link(row['href'], _('Open %(unit)s') % {'unit': unit.code}, 'search')]
        if can_edit:
            actions.append(L.link(reverse('farm:tank_edit', args=[unit.pk]), _('Edit %(name)s') % {'name': unit.code},
                                  'pencil'))
        status = 'critical' if water and water.status == 'critical' else (
            'warning' if (water and water.status == 'warning') or (stock and stock.over_capacity) else None)
        rows.append(L.row(unit.pk, cells, actions, status=status))
    filters = []
    if context['site_buttons']:
        filters.append(_buttons_choice('site', _('Site'), context['site_buttons'], params))
    if len(context['kind_buttons']) > 2:
        filters.append(_buttons_choice('kind', _('Kind'), context['kind_buttons'], params, first=_('All kinds')))
    filters.append(_buttons_choice('occupancy', _('Fish'), context['occupancy_buttons'], params,
                                   first=_('Stocked and empty')))
    filters.append(L.choice('status', _('Status'), context['chosen_status'],
                            [('', _('All statuses')), *context['statuses']]))
    if not context['units']:
        setup = {'href': reverse('farm:tank_list'), 'label': _('Add them in Setup › Tanks, ponds & cages.')} \
            if context['can_setup'] else None
        empty = {'title': _('No production units yet'), 'text': _('Fish are held in the tanks, ponds and cages of Setup.'),
                 'link': setup, 'add': None}
    else:
        empty = {'title': _('No units match these filters.'), 'text': None,
                 'link': {'href': context['clear_url'], 'label': _('Clear filters')}, 'add': None}
    search = _('Search unit, batch or species')
    here = request.get_full_path()
    return {
        'csrfToken': '',
        'tabs': L.tabs(_('Fish'), [(here, _('Production'),
                                    context['stocked'], True)]),
        'toolbar': {'label': search, 'search': {'name': 'q', 'value': context['query'], 'label': search, 'placeholder': search},
                    'keep': [{'name': 'unit', 'value': params['unit']}] if params['unit'] else [],
                    'filters': filters, 'submit': _('Filter'), 'add': None},
        'notices': [],
        # the bFCR column's explanation (the classic header's abbreviation title), said above the table
        'lines': [f"{_('bFCR')}: {_(FCR_SAID)}"] if show_feeding and context['rows'] else [],
        'table': {'label': _('Production units, scrolls sideways'), 'columns': columns, 'rows': rows,
                  'actionsLabel': _('Actions')},
        'empty': empty,
        'pager': None,
    }


def _buttons_choice(name, label, buttons, params, first=None):
    """The classic page's row of filter buttons ("All" and one per option, farm.stock.views._buttons) as a select of the
    same values: the first is "All" (or `first`, the design's "All kinds" where a bare "All" in a select would not say
    of what), each other the value its link sets."""
    from urllib.parse import parse_qs, urlsplit
    options = []
    for at, button in enumerate(buttons):
        value = parse_qs(urlsplit(button['href']).query).get(name, [''])[0]
        options.append((value, first if at == 0 and first is not None else button['label']))
    return L.choice(name, label, params[name], options)


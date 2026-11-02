"""Operations › Production units: every tank, pond and cage of Setup with the fish in it now, and the
operations on them (the platform's /sites/tanks). It is a read page, not a CRUD tab: one table, a
drawer for the unit picked (`?unit=`), and the operation dialogs, each a URL that renders its form in
the shared dialog (templates/modal_base.html, frontend/components.ts) or as a page, posts to itself
and goes back to the page with the drawer open (core.crud.done).

Every filter and the open drawer live in the query string, so a view can be linked to and the back
button works. Who may do what: reading the page needs view on the stock operations, recording one
add, voiding one delete (config/access.py); the buttons a person cannot use are not shown, and the
views refuse them too."""
import uuid
from urllib.parse import urlencode

from django.contrib import messages
from django.contrib.auth.decorators import permission_required
from django.core.exceptions import ValidationError
from django.db.models import Prefetch
from django.http import Http404
from django.shortcuts import get_object_or_404
from django.urls import reverse
from django.utils.translation import gettext as _, gettext_lazy, ngettext, pgettext

from core import navigation
from core.crud import done, render_page

from ..forms.stock import (
    BatchInputForm, CullForm, GradingForm, HarvestForm, InputLineFormSet, MortalityForm, TransferForm, VoidForm,
    WeighingForm, kept_rows, stockable_units,
)
from ..models import StockMovement, StockOperation, Tank
from ..models.stock import ARRIVAL_STATUSES
from ..templatetags.stock import fish, number, tonnes
from . import read, services
from .services import AlreadyRecorded

VIEW, RECORD, VOID = 'farm.view_stockoperation', 'farm.add_stockoperation', 'farm.delete_stockoperation'
FILTERS = ('q', 'site', 'kind', 'occupancy', 'status')
NO_SITE = 'none'
STOCKED, EMPTY = 'stocked', 'empty'
HISTORY = 20    # operations listed in the drawer


# ---- the query string ----------------------------------------------------------------------------
def _params(request):
    return {key: request.GET.get(key, '').strip() for key in (*FILTERS, 'unit')}


def page_url(params, **changes):
    """The page with these filters (and drawer), one or more of them changed; empty ones left out."""
    merged = {**params, **changes}
    query = urlencode({key: value for key, value in merged.items() if value and key in (*FILTERS, 'unit')})
    return reverse('farm:production_units') + (f'?{query}' if query else '')


def _query(params, **changes):
    merged = {**params, **changes}
    return urlencode({key: value for key, value in merged.items() if value and key in (*FILTERS, 'unit')})


def _place():
    place = navigation.place(VIEW)
    return place.entry.label, place.section.label


def _context(**extra):
    title, section = _place()
    return {'title': title, 'eyebrow': f'{section} · {title}', **extra}


# ---- the page ------------------------------------------------------------------------------------
def _site_key(unit):
    site = unit.production_department.site
    return str(site.pk) if site else NO_SITE


def _matches(unit, stock, params):
    site, kind, occupancy, status, query = (params[key] for key in ('site', 'kind', 'occupancy', 'status', 'q'))
    if site and _site_key(unit) != site:
        return False
    if kind and unit.kind != kind:
        return False
    if occupancy == STOCKED and stock is None or occupancy == EMPTY and stock is not None:
        return False
    if status and unit.status != status:
        return False
    if query:
        words = [unit.code, unit.name]
        if stock is not None:
            for batch in stock.batches:
                words += [batch.code, batch.name, batch.species.common_name, batch.species.local_name,
                          batch.species.scientific_name]
        return any(query.lower() in word.lower() for word in words if word)
    return True


def _clean(params, units):
    """Drops a filter value that names nothing there is (a stale link shows everything, as the tabs do)."""
    valid = {
        'site': {_site_key(unit) for unit in units},
        'kind': set(Tank.Kind.values), 'occupancy': {STOCKED, EMPTY}, 'status': set(Tank.Status.values),
        'unit': {str(unit.pk) for unit in units},
    }
    return {key: value if key not in valid or value in valid[key] else '' for key, value in params.items()}


def _buttons(params, key, options, all_label):
    """A row of filter buttons: "All" and one per option, each a link that changes only this filter."""
    return [{'label': all_label, 'href': page_url(params, **{key: ''}), 'pressed': not params[key]}] + [
        {'label': label, 'href': page_url(params, **{key: value}), 'pressed': params[key] == value}
        for value, label in options]


@permission_required(VIEW, raise_exception=True)
def production_units(request):
    units = list(Tank.objects.select_related('production_department__site', 'system'))
    units.sort(key=lambda unit: (unit.production_department.site.name if unit.production_department.site else '',
                                 unit.production_department.name, unit.code))
    stock = read.stock_of(units)
    params = _clean(_params(request), units)
    shown = [unit for unit in units if _matches(unit, stock.get(unit.pk), params)]

    sites = {}
    for unit in units:
        site = unit.production_department.site
        sites[_site_key(unit)] = site.name if site else _('No site')
    site_options = sorted(((key, name) for key, name in sites.items() if key != NO_SITE), key=lambda item: item[1])
    if NO_SITE in sites:
        site_options.append((NO_SITE, sites[NO_SITE]))
    kinds_present = {unit.kind for unit in units}
    biomass = sum((stock[unit.pk].biomass_kg for unit in shown if unit.pk in stock), start=0)
    drawer_unit = next((unit for unit in units if str(unit.pk) == params['unit']), None)

    context = _context(
        units=units, stocked=len(stock),
        rows=[{'unit': unit, 'stock': stock.get(unit.pk), 'selected': unit is drawer_unit,
               'href': page_url(params, unit=str(unit.pk)), 'takes_fish': unit.status in ARRIVAL_STATUSES}
              for unit in shown],
        biomass=biomass,
        count_line=ngettext('%(count)d unit', '%(count)d units', len(shown)) % {'count': len(shown)},
        params=params, query=params['q'],
        search_hidden=[(key, params[key]) for key in (*FILTERS, 'unit') if key != 'q' and params[key]],
        status_hidden=[(key, params[key]) for key in (*FILTERS, 'unit') if key != 'status' and params[key]],
        site_buttons=_buttons(params, 'site', site_options, _('All sites')) if len(site_options) > 1 else [],
        kind_buttons=_buttons(params, 'kind', [(value, label) for value, label in _kind_options()
                                               if value in kinds_present], _('All')),
        occupancy_buttons=_buttons(
            params, 'occupancy', [(STOCKED, pgettext('occupancy', 'Stocked')), (EMPTY, _('Empty'))], _('All')),
        statuses=Tank.Status.choices, chosen_status=params['status'],
        clear_url=page_url({}, unit=params['unit']),
        can_record=request.user.has_perm(RECORD), can_void=request.user.has_perm(VOID),
        can_setup=request.user.has_perm('farm.view_tank'),
        new_batch_url=reverse('farm:stock_input') + _with_query(_query(params, unit='')),
    )
    if drawer_unit is not None:
        context.update(_drawer(request, drawer_unit, stock.get(drawer_unit.pk), params))
    return render_page(request, 'farm/production_units.html', context)


def _kind_options():
    """The kind filter's buttons, in the plural (the source's labels)."""
    return [(Tank.Kind.TANK, _('Tanks')), (Tank.Kind.POND, _('Ponds')), (Tank.Kind.CAGE, _('Cages'))]


def _with_query(query):
    return f'?{query}' if query else ''


def _drawer(request, unit, stock, params):
    """The drawer of one unit: its fish, the operations that make sense for it, its recent history."""
    query = _with_query(_query(params, unit=str(unit.pk)))
    can_record, can_void = request.user.has_perm(RECORD), request.user.has_perm(VOID)
    operations = (StockOperation.all_objects.filter(movements__unit=unit).distinct()
                  .select_related('created_by', 'deleted_by')
                  .prefetch_related(Prefetch('movements', StockMovement.objects.select_related('unit', 'batch')))
                  .order_by('-date', '-created_at')[:HISTORY])
    earliest = services.earliest(unit)
    history = [{'operation': operation, 'lines': list(operation.movements.all()),
                'void_url': reverse('farm:stock_void', args=[operation.pk]) + query
                if can_void and not operation.is_deleted and operation.date >= earliest else ''}
               for operation in operations]
    takes_fish = unit.status in ARRIVAL_STATUSES
    actions = []
    if can_record and stock is not None:
        actions = [{'label': heading, 'url': reverse(f'farm:stock_{kind}', args=[unit.pk]) + query,
                    'primary': kind == 'mortality'} for kind, (_form, heading) in OPERATIONS.items()]
        if takes_fish:
            actions.append({'label': _('Stock another batch'), 'url': reverse('farm:stock_input') + query})
    return {
        'drawer': unit, 'drawer_stock': stock, 'history': history, 'actions': actions,
        'drawer_days': stock.days(services.local_today(unit)) if stock else None,
        'stock_url': reverse('farm:stock_input') + query if can_record and takes_fish else '',
        'close_url': page_url(params, unit=''),
        'takes_fish': takes_fish,
        'edit_unit_url': reverse('farm:tank_edit', args=[unit.pk]) if request.user.has_perm('farm.change_tank') else '',
    }


# ---- the dialogs ---------------------------------------------------------------------------------
def _back(request, unit=None):
    """Back to the page, filters kept, with the drawer of `unit` open."""
    params = _params(request)
    return page_url(params, unit=str(unit.pk) if unit is not None else params['unit'])


def _refused(request, template, context):
    """The form again, with the reasons it was not saved."""
    response = render_page(request, template, context)
    response.status_code = 422
    return response


@permission_required(RECORD, raise_exception=True)
def stock_input(request):
    """A new batch, into one unit (the drawer's, preselected) or several."""
    chosen = request.GET.get('unit', '')
    preselected = Tank.objects.filter(pk=chosen).first() if _is_uuid(chosen) else None
    kwargs = {'form_kwargs': _unit_choices(stockable_units()), 'prefix': 'units'}
    heading = (_('Stock unit %(unit)s') % {'unit': preselected.code} if preselected and
               preselected.status in ARRIVAL_STATUSES else _('New batch'))
    if request.method == 'POST':
        form = BatchInputForm(request.POST)
        rows = InputLineFormSet(request.POST, **kwargs)
        lines = _lines(form, rows)
        if lines is not None:
            try:
                operation = form.save(request.user, lines)
            except AlreadyRecorded as recorded:
                return done(request, _back(request, _first_unit(recorded.operation)))
            except ValidationError as error:
                form.add_service_error(error)
            else:
                batch = operation.movements.first().batch
                messages.success(request, _('Batch %(batch)s stocked: %(count)s fish into %(units)s.') % {
                    'batch': batch.code, 'count': number(form.cleaned_data['count']),
                    'units': ', '.join(unit.code for unit, _count in lines)})
                return done(request, _back(request, lines[0][0]))
        return _refused(request, 'farm/stock_input.html', _context(form=form, rows=rows, heading=heading,
                                                                   back_url=_back(request)))
    form = BatchInputForm(unit=preselected)
    initial = [{'unit': preselected.pk}] if preselected and preselected.status in ARRIVAL_STATUSES else []
    rows = InputLineFormSet(initial=initial, **kwargs)
    return render_page(request, 'farm/stock_input.html', _context(form=form, rows=rows, heading=heading,
                                                                  back_url=_back(request)))


def _is_uuid(value):
    try:
        uuid.UUID(str(value))
    except ValueError:
        return False
    return True


def _unit_choices(units):
    """The units a row of a form can send fish to, each labelled with its room (form_kwargs of the rows)."""
    stock = read.stock_of(list(units))
    return {'units': units, 'labels': {unit.pk: _unit_choice(unit, stock.get(unit.pk)) for unit in units}}


def _unit_choice(unit, stock):
    """A unit in the stocking form's list: its code, name and room: T-01 · Start tank — 820 kg free."""
    if stock is None:
        room = _('empty, %(max)s kg max') % {'max': number(unit.max_biomass_kg or 0)}
    else:
        free = (unit.max_biomass_kg or 0) - stock.biomass_kg
        room = _('%(free)s kg free') % {'free': number(max(free, 0))}
    return f'{unit.code} · {unit.name} — {room}'


def _lines(form, rows):
    """[(unit, fish)] when the form and its rows are valid and add up; None otherwise (errors set)."""
    form_valid, rows_valid = form.is_valid(), rows.is_valid()
    if not (form_valid and rows_valid):
        return None
    lines = [(row.cleaned_data['unit'], row.cleaned_data['count']) for row in rows.forms
             if row.cleaned_data and row.cleaned_data.get('unit')]
    if not lines:
        form.add_error(None, _('Choose the unit the fish go into.'))
        return None
    units = [unit for unit, _count in lines]
    if len(set(units)) != len(units):
        form.add_error(None, _('Each unit can be listed once.'))
        return None
    placed = sum(count for _unit, count in lines)
    if placed != form.cleaned_data['count']:
        form.add_error('count', _('The units take %(placed)s fish, but %(count)s arrive: the split must add up.') % {
            'placed': number(placed), 'count': number(form.cleaned_data['count'])})
        return None
    return lines


def _first_unit(operation):
    line = operation.movements.order_by('id').first()
    return line.unit if line else None


# The operations on a unit's fish, in the order the drawer offers them: kind -> (form, heading).
OPERATIONS = {
    'mortality': (MortalityForm, gettext_lazy('Record mortality')),
    'weighing': (WeighingForm, gettext_lazy('Sampling weigh-in')),
    'transfer': (TransferForm, gettext_lazy('Transfer / split')),
    'grading': (GradingForm, gettext_lazy('Grading')),
    'cull': (CullForm, gettext_lazy('Record cull')),
    'harvest': (HarvestForm, gettext_lazy('Harvest')),
}


def _recorded(operation):
    """What the flash message says after an operation."""
    lines = list(operation.movements.select_related('unit', 'batch'))
    line = lines[0]
    params = {'count': number(abs(line.count_delta)), 'batch': line.batch.code, 'unit': line.unit.code}
    if operation.kind == 'mortality':
        return _('Mortality recorded: %(count)s fish of %(batch)s in %(unit)s.') % params
    if operation.kind == 'cull':
        return _('Cull recorded: %(count)s fish of %(batch)s in %(unit)s.') % params
    if operation.kind in ('transfer', 'grading'):
        moved = [item for item in lines if item.kind == 'transfer_in']
        text = (_('Transfer recorded: %(count)s fish of %(batch)s from %(unit)s to %(units)s.')
                if operation.kind == 'transfer' else
                _('Grading recorded: %(count)s fish of %(batch)s from %(unit)s to %(units)s.'))
        return text % {**params, 'count': number(sum(item.count_delta for item in moved)),
                       'units': ', '.join(item.unit.code for item in moved)}
    if operation.kind == 'harvest':
        harvest = next(item for item in lines if item.kind == 'harvest')
        return _('Harvest recorded: %(count)s fish of %(batch)s from %(unit)s, %(kilos)s kg weighed.') % {
            **params, 'count': number(-harvest.count_delta), 'kilos': number(harvest.measured_weight_kg, 1)}
    return _('Weighing recorded: %(batch)s in %(unit)s, average %(weight)s g.') % {
        **params, 'weight': number(line.avg_weight_g, 2)}


@permission_required(RECORD, raise_exception=True)
def record_operation(request, pk, kind):
    """An operation on the fish of one unit: mortality, a weighing, a transfer or split, a grading, a cull,
    a harvest. A transfer and a grading list the units the fish go into as rows (any unit that takes
    fish but this one)."""
    if kind not in OPERATIONS:
        raise Http404
    unit = get_object_or_404(Tank.objects.select_related('production_department__site'), pk=pk)
    form_class, heading = OPERATIONS[kind]
    stock = read.stock_of([unit]).get(unit.pk)
    present = stock.shares if stock else []
    context = _context(unit=unit, stock=stock, heading=heading, back_url=_back(request, unit))
    if not present:
        return render_page(request, 'farm/stock_operation.html', context)
    row_kwargs = {'form_kwargs': _unit_choices(stockable_units().exclude(pk=unit.pk)), 'prefix': 'rows'}
    if request.method == 'POST':
        form = form_class(request.POST, unit=unit, present=present)
        rows = form_class.rows(request.POST, **row_kwargs) if form_class.rows else None
        valid = form.is_valid() & (rows is None or rows.is_valid())
        if valid:
            try:
                operation = form.save(request.user, kept_rows(rows) if rows is not None else None)
            except AlreadyRecorded:
                return done(request, _back(request, unit))
            except ValidationError as error:
                form.add_service_error(error)
            else:
                messages.success(request, _recorded(operation))
                return done(request, _back(request, unit))
        return _refused(request, 'farm/stock_operation.html', {**context, 'form': form, 'rows': rows})
    form = form_class(unit=unit, present=present)
    if request.GET.get('batch') in form.present:
        form.initial['batch'] = request.GET['batch']
    rows = form_class.rows(**row_kwargs) if form_class.rows else None
    return render_page(request, 'farm/stock_operation.html', {**context, 'form': form, 'rows': rows})


@permission_required(VOID, raise_exception=True)
def void_operation(request, pk):
    """Voids an operation, with the reason."""
    operation = get_object_or_404(StockOperation, pk=pk)
    lines = list(operation.movements.select_related('unit', 'batch'))
    chosen = _params(request)['unit']
    unit = Tank.all_objects.filter(pk=chosen).first() if _is_uuid(chosen) else None
    context = _context(operation=operation, lines=lines, heading=_('Void operation'),
                       back_url=_back(request, unit))
    if request.method == 'POST':
        form = VoidForm(request.POST)
        if form.is_valid():
            try:
                services.void(request.user, operation, form.cleaned_data['reason'])
            except ValidationError as error:
                form.add_service_error(error)
            else:
                messages.success(request, _('%(operation)s of %(date)s voided.') % {
                    'operation': operation.get_kind_display(), 'date': services.shown_date(operation.date)})
                return done(request, _back(request, unit))
        return _refused(request, 'farm/stock_void.html', {**context, 'form': form})
    return render_page(request, 'farm/stock_void.html', {**context, 'form': VoidForm()})


def overview_tiles(user):
    """The production overview's stock figures: units with fish, fish, biomass (for people who may
    read the stock)."""
    if not user.has_perm(VIEW):
        return []
    units = list(Tank.objects.all())
    stock = read.stock_of(units)
    url = reverse('farm:production_units')
    return [
        {'label': _('Stocked units'), 'count': len(stock), 'url': f'{url}?occupancy={STOCKED}'},
        {'label': _('Fish'), 'count': fish(sum(item.count for item in stock.values())), 'url': url},
        {'label': _('Biomass'), 'count': tonnes(sum((item.biomass_kg for item in stock.values()), start=0)),
         'url': url},
    ]

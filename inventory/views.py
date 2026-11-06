"""Operations › Storage: the store's page and its dialogs (the platform's /sites/storage). A read page with
four tabs in the address (`?tab=`): Overview (per site and item the stock, its days of cover and the
feeding beyond the book; low stock, over capacity, expiring and expired lots, the value per currency),
Stock (a row per lot in a location, with its actions prefilled), Movements (the operations, and the
feeding read from the records) and Counts (each count with its variance worked out on read). An item's
day-by-day book and a lot's trace have pages of their own.

The dialogs are the stock's (farm/stock/views.py): the shared dialog or a page, the form posted to itself,
the server's reasons on their fields (422), back to the page they came from (`next`). Who may do what: the
area Storage (config/access.py): Read the page, Create records an operation, Delete voids one; the
buttons a person cannot use are not shown, and the views refuse them too."""
from collections import defaultdict
from urllib.parse import urlencode

from django.contrib import messages
from django.contrib.auth.decorators import permission_required
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.db.models import Q, Sum
from django.http import Http404
from django.shortcuts import get_object_or_404
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.utils.translation import gettext as _, gettext_lazy, ngettext

from core import navigation
from core.crud import DRAFT, done, render_page
from core.dates import read_day
from farm.forms.stock import VoidForm
from farm.models import Feed, FeedingRecord, Site, Supplier
from farm.stock.dates import shown_date, site_earliest, site_today
from farm.stock.services import AlreadyRecorded
from farm.stock.views import _is_uuid, _refused
from farm.templatetags.feeding import amount

from . import read, services
from .forms import (
    CountForm, CountLineFormSet, FoundLotFormSet, IssueForm, ReceiptForm, ReceiptLineFormSet, ReturnForm,
    TransferForm, WriteOffForm, kept_rows,
)
from .models import InventoryItem, InventoryLine, InventoryLot, InventoryOperation, OperationKind, StorageLocation

VIEW, RECORD, VOID = 'inventory.view_inventoryoperation', 'inventory.add_inventoryoperation', \
    'inventory.delete_inventoryoperation'
TABS = [('overview', gettext_lazy('Overview')), ('stock', gettext_lazy('Stock')),
        ('movements', gettext_lazy('Movements')), ('counts', gettext_lazy('Counts'))]
FEEDING = 'feeding'     # the movements' kind filter for the feeding read from the records
PAGE_SIZE = 50
COUNTS_PAGE = 20


def _context(**extra):
    place = navigation.place(VIEW)
    return {'title': place.entry.label, 'eyebrow': f'{place.section.label} · {place.entry.label}', **extra}


def _back(request):
    """The page a dialog came from (`next`), else the storage page."""
    target = request.GET.get('next', '')
    if target.startswith('/') and url_has_allowed_host_and_scheme(target, allowed_hosts={request.get_host()}):
        return target
    return reverse('inventory:storage')


def _with_next(url, request, **params):
    return f'{url}?{urlencode({**params, "next": request.get_full_path()})}'


# ---- the page ------------------------------------------------------------------------------------
@permission_required(VIEW, raise_exception=True)
def storage(request):
    tab = request.GET.get('tab', '')
    tab = tab if tab in dict(TABS) else 'overview'
    can_record = request.user.has_perm(RECORD)
    actions = []
    if can_record:
        actions = [{'label': label, 'url': _with_next(reverse(f'inventory:{name}'), request), 'primary': index == 0}
                   for index, (name, label) in enumerate([
                       ('receive', _('Receive delivery')), ('transfer', _('Transfer')), ('issue', _('Issue')),
                       ('write_off', _('Write off')), ('return', _('Return to supplier')),
                       ('count', _('Count a location'))])]
    context = _context(tab=tab, tabs=[{'key': key, 'label': label, 'url': f'{reverse("inventory:storage")}?tab={key}',
                                       'current': key == tab} for key, label in TABS],
                       actions=actions, can_record=can_record, can_void=request.user.has_perm(VOID))
    context.update({'overview': _overview, 'stock': _stock, 'movements': _movements, 'counts': _counts}[tab](
        request, context))
    return render_page(request, 'inventory/storage.html', context)


def _overview(request, context):
    found = read.overview()
    return {'summary': found, 'feeding_url': reverse('farm:feeding_records')}


def _stock(request, context):
    params = {key: request.GET.get(key, '').strip() for key in ('site', 'location', 'item', 'empty')}
    rows = read.buckets(empty=params['empty'] == '1')
    sites = sorted({row.site for row in rows}, key=lambda site: site.name)
    locations = sorted({row.location for row in rows}, key=lambda location: location.code)
    items = sorted({row.item for row in rows}, key=str)
    for key, choices in (('site', sites), ('location', locations), ('item', items)):
        if params[key] not in {str(choice.pk) for choice in choices}:
            params[key] = ''
    shown = [row for row in rows if (not params['site'] or str(row.site.pk) == params['site'])
             and (not params['location'] or str(row.location.pk) == params['location'])
             and (not params['item'] or str(row.item.pk) == params['item'])]
    totals = defaultdict(lambda: 0)
    for row in shown:
        totals[(row.site, row.item)] += row.quantity
    can_record = context['can_record']
    here = request.get_full_path()

    def act(name, row):
        return f'{reverse(f"inventory:{name}")}?{urlencode({"location": row.location.pk, "lot": row.lot.pk, "next": here})}'

    return {
        'params': params, 'sites': sites, 'locations': locations, 'items': items,
        'rows': [{'bucket': row, 'expired': row.lot.expiry_date is not None and row.lot.expiry_date < site_today(row.site),
                  'actions': [(act(name, row), label) for name, label in (
                      ('transfer', _('Transfer')), ('issue', _('Issue')), ('write_off', _('Write off')),
                      ('return', _('Return'))) if can_record and row.quantity > 0],
                  'item_url': f'{reverse("inventory:item", args=[row.item.pk])}?site={row.site.pk}',
                  'lot_url': reverse('inventory:lot', args=[row.lot.pk])} for row in shown],
        'totals': [{'site': site, 'item': item, 'quantity': quantity}
                   for (site, item), quantity in sorted(totals.items(), key=lambda entry: (entry[0][0].name, str(entry[0][1])))],
        'filtered': any(params.values()),
    }


def _movements(request, context):
    params = {key: request.GET.get(key, '').strip()
              for key in ('site', 'location', 'kind', 'item', 'supplier', 'from', 'to', 'voided')}
    choices = {
        'site': Site.objects.filter(storage_locations__isnull=False).distinct().order_by('name'),
        'location': StorageLocation.all_objects.filter(lines__isnull=False).distinct().order_by('code'),
        'item': InventoryItem.all_objects.select_related('feed').order_by('feed__name'),
        'supplier': Supplier.all_objects.filter(inventory_operations__isnull=False).distinct().order_by('name'),
    }
    for key in choices:
        if params[key] not in {str(pk) for pk in choices[key].values_list('pk', flat=True)}:
            params[key] = ''
    if params['kind'] not in (*OperationKind.values, FEEDING):
        params['kind'] = ''
    for key in ('from', 'to'):
        day = read_day(params[key])
        params[key] = day or ''          # a date: the input shows it as the language writes it
    if params['voided'] != '1':
        params['voided'] = ''
    kept = {key: value for key, value in params.items() if value}
    pager_query = urlencode({'tab': 'movements', **kept})
    common = {'params': params, 'choices': choices, 'kinds': [*OperationKind.choices, (FEEDING, _('Feeding (from the records)'))],
              'pager_query': pager_query, 'filtered': bool({key for key in kept if key != 'voided'})}
    if params['kind'] == FEEDING:
        return {**common, **_feeding_days(params)}
    operations = InventoryOperation.all_objects.select_related(
        'supplier', 'location', 'created_by', 'deleted_by').prefetch_related('lines__location__site', 'lines__lot__item__feed')
    if not params['voided']:
        operations = operations.filter(is_deleted=False)
    if params['site']:
        operations = operations.filter(Q(lines__location__site=params['site']) | Q(location__site=params['site']))
    if params['location']:
        operations = operations.filter(Q(lines__location=params['location']) | Q(location=params['location']))
    if params['kind']:
        operations = operations.filter(kind=params['kind'])
    if params['item']:
        operations = operations.filter(lines__lot__item=params['item'])
    if params['supplier']:
        operations = operations.filter(supplier=params['supplier'])
    if params['from']:
        operations = operations.filter(date__gte=params['from'])
    if params['to']:
        operations = operations.filter(date__lte=params['to'])
    operations = operations.distinct().order_by('-date', '-created_at')
    page = Paginator(operations, PAGE_SIZE).get_page(request.GET.get('page'))
    here = request.get_full_path()
    return {**common, 'page': page, 'operations': [
        {'operation': operation, 'lines': list(operation.lines.all()),
         'void_url': f'{reverse("inventory:void", args=[operation.pk])}?{urlencode({"next": here})}'
         if context['can_void'] and _voidable(operation) else ''}
        for operation in page.object_list]}


def _voidable(operation):
    """Not voided yet, and within the backdating window of every site it touches."""
    if operation.is_deleted:
        return False
    sites = {line.location.site for line in operation.lines.all()}
    if operation.location_id:
        sites.add(operation.location.site)
    return all(operation.date >= site_earliest(site) for site in sites)


def _feeding_days(params):
    """The feeding of each site, feed and day, read from the records: what the store's book draws."""
    rows = FeedingRecord.objects.filter(unit__production_department__site__isnull=False)
    if params['site']:
        rows = rows.filter(unit__production_department__site=params['site'])
    if params['item']:
        rows = rows.filter(feed__inventory_items=params['item'])
    if params['from']:
        rows = rows.filter(date__gte=params['from'])
    if params['to']:
        rows = rows.filter(date__lte=params['to'])
    rows = (rows.order_by().values('unit__production_department__site', 'feed', 'date').annotate(kg=Sum('amount_kg'))
            .order_by('-date', 'unit__production_department__site', 'feed'))
    feeds, sites = Feed.all_objects.in_bulk(), Site.all_objects.in_bulk()
    url = reverse('farm:feeding_records')
    return {'feeding_rows': [
        {'date': row['date'], 'site': sites[row['unit__production_department__site']], 'feed': feeds[row['feed']],
         'kilos': row['kg'], 'url': f'{url}?{urlencode({"site": row["unit__production_department__site"], "feed": row["feed"], "from": row["date"].isoformat(), "to": row["date"].isoformat()})}'}
        for row in rows]}


def _counts(request, context):
    counts = (InventoryOperation.all_objects.filter(kind=OperationKind.COUNT)
              .select_related('location__site', 'created_by', 'deleted_by').order_by('-date', '-created_at'))
    page = Paginator(counts, COUNTS_PAGE).get_page(request.GET.get('page'))
    here = request.get_full_path()
    return {'page': page, 'pager_query': urlencode({'tab': 'counts'}), 'counts': [
        {'operation': operation, 'variances': read.count_variances(operation),
         'void_url': f'{reverse("inventory:void", args=[operation.pk])}?{urlencode({"next": here})}'
         if context['can_void'] and not operation.is_deleted and operation.date >= site_earliest(operation.location.site)
         else ''}
        for operation in page.object_list],
        'count_url': _with_next(reverse('inventory:count'), request) if context['can_record'] else ''}


@permission_required(VIEW, raise_exception=True)
def item_page(request, pk):
    """An item's day-by-day book at one of its sites: what arrived, left, was fed, beyond the book, counted."""
    item = get_object_or_404(InventoryItem.all_objects.select_related('feed'), pk=pk)
    sites = read.item_sites(item)
    chosen = request.GET.get('site', '')
    site = next((site for site in sites if str(site.pk) == chosen), sites[0] if sites else None)
    return render_page(request, 'inventory/item.html', _context(
        item=item, sites=sites, site=site, days=read.item_days(item, site) if site else [],
        back_url=f'{reverse("inventory:storage")}?tab=stock'))


@permission_required(VIEW, raise_exception=True)
def lot_page(request, pk):
    """A lot's trace: the deliveries that brought it and from whom, where it moved, what left, its counts,
    and the feeding estimated to have drawn it."""
    lot = get_object_or_404(InventoryLot.all_objects.select_related('item__feed'), pk=pk)
    lines, fed = read.lot_trace(lot)
    return render_page(request, 'inventory/lot.html', _context(
        lot=lot, lines=lines, fed=fed, item_url=reverse('inventory:item', args=[lot.item_id]),
        back_url=f'{reverse("inventory:storage")}?tab=stock'))


# ---- the dialogs ---------------------------------------------------------------------------------
def _recorded(operation):
    """What the flash message says after an operation."""
    lines = list(operation.lines.select_related('location', 'lot__item__feed'))
    if operation.kind == OperationKind.RECEIPT:
        return ngettext('Delivery from %(supplier)s recorded: %(count)d line.',
                        'Delivery from %(supplier)s recorded: %(count)d lines.', len(lines)) % {
            'supplier': operation.supplier, 'count': len(lines)}
    if operation.kind == OperationKind.COUNT:
        return _('Count of %(location)s on %(date)s recorded.') % {
            'location': operation.location.code, 'date': shown_date(operation.date)}
    line = next(line for line in lines if line.quantity < 0)
    params = {'quantity': amount(-line.quantity), 'unit': line.lot.item.get_unit_display(), 'item': line.lot.item,
              'location': line.location.code, 'operation': operation.get_kind_display()}
    return _('%(operation)s recorded: %(quantity)s %(unit)s of %(item)s from %(location)s.') % params


@permission_required(RECORD, raise_exception=True)
def receive(request):
    """A delivery from a supplier, in one or several lines."""
    back = _back(request)
    context = _context(heading=_('Receive delivery'), back_url=back, rows_label=_('What was delivered'),
                       add_label=_('Add line'))
    if request.method == 'POST':
        form, rows = ReceiptForm(request.POST), ReceiptLineFormSet(request.POST, prefix='lines')
        if form.is_valid() & rows.is_valid():
            lines = kept_rows(rows)
            if not lines:
                form.add_error(None, _('List what was delivered.'))
            else:
                try:
                    operation = form.save(request.user, lines)
                except AlreadyRecorded:
                    return done(request, back)
                except ValidationError as error:
                    form.add_service_error(error)
                else:
                    messages.success(request, _recorded(operation))
                    return done(request, back)
        return _refused(request, 'inventory/dialog.html', {**context, 'form': form, 'rows': rows})
    return render_page(request, 'inventory/dialog.html', {**context, 'form': ReceiptForm(),
                                                          'rows': ReceiptLineFormSet(prefix='lines')})


DEPARTURES = {
    'issue': (IssueForm, gettext_lazy('Issue')),
    'write_off': (WriteOffForm, gettext_lazy('Write off')),
    'return': (ReturnForm, gettext_lazy('Return to supplier')),
    'transfer': (TransferForm, gettext_lazy('Transfer')),
}


@permission_required(RECORD, raise_exception=True)
def departure(request, kind):
    """A lot leaving a location: an issue, a write-off, a return to the supplier or a transfer; from a stock
    row the lot and its location are chosen (`?location=&lot=`)."""
    if kind not in DEPARTURES:
        raise Http404
    form_class, heading = DEPARTURES[kind]
    back = _back(request)
    buckets = [row for row in read.buckets() if row.quantity > 0]
    chosen = f'{request.GET.get("location", "")}:{request.GET.get("lot", "")}'
    preset = next((row for row in buckets if f'{row.location.pk}:{row.lot.pk}' == chosen), None)
    context = _context(heading=heading, back_url=back)
    if request.method == 'POST':
        form = form_class(request.POST, buckets=buckets)
        if form.is_valid():
            try:
                operation = form.save(request.user)
            except AlreadyRecorded:
                return done(request, back)
            except ValidationError as error:
                form.add_service_error(error)
            else:
                messages.success(request, _recorded(operation))
                return done(request, back)
        return _refused(request, 'inventory/dialog.html', {**context, 'form': form})
    form = form_class(buckets=buckets, site=preset.site if preset else None)
    if preset is not None:
        form.initial['source'] = chosen
        if kind == 'return':
            first = (InventoryLine.objects.filter(lot=preset.lot, kind='in', operation__is_deleted=False)
                     .select_related('operation').order_by('operation__date', 'id').first())
            if first is not None:
                form.initial['supplier'] = first.operation.supplier_id
    if not buckets:
        context['empty'] = _('Nothing is in stock: receive a delivery first.')
    return render_page(request, 'inventory/dialog.html', {**context, 'form': form})


@permission_required(RECORD, raise_exception=True)
def count(request):
    """A count of one location at the end of a day: the lots the book has there then, each to be filled in
    (0 when none is left), and the lots found that the book did not have there. Choosing the location or the
    day renders the form again with what was entered (core.crud's draft); nothing is saved until it is sent."""
    back = _back(request)
    context = _context(heading=_('Count a location'), back_url=back, rows_label=_('Found, not in the book'),
                       add_label=_('Add a lot'))
    if request.method == 'POST' and DRAFT not in request.POST:
        form = CountForm(request.POST)
        lines = CountLineFormSet(request.POST, prefix='lots')
        rows = FoundLotFormSet(request.POST, prefix='found')
        if form.is_valid() & lines.is_valid() & rows.is_valid():
            try:
                operation = services.count(
                    request.user, location=form.cleaned_data['location'], day=form.cleaned_data['date'],
                    lines=[(line.cleaned_data['lot'], line.cleaned_data['quantity']) for line in lines.forms],
                    found=[(row['feed'], row['lot_number'], row['expiry_date'], row['quantity'])
                           for row in kept_rows(rows)],
                    notes=form.cleaned_data['notes'], token=form.cleaned_data['token'])
            except AlreadyRecorded:
                return done(request, back)
            except ValidationError as error:
                form.add_service_error(error)
            else:
                messages.success(request, _recorded(operation))
                return done(request, back)
        location, day = _location(request.POST.get('location')), read_day(request.POST.get('date', ''))
        return _refused(request, 'inventory/count.html', {
            **context, 'form': form, 'lines': lines, 'rows': rows, 'location': location,
            'pairs': _pairs(lines, read.book_at(location, day) if location and day else [])})
    data = request.POST if request.method == 'POST' else {}
    location = _location(data.get('location', request.GET.get('location', '')))
    day = read_day(data.get('date', '')) or (site_today(location.site) if location else None)
    form = CountForm(initial={'location': location.pk if location else None, 'date': day,
                              'notes': data.get('notes', '')}, site=location.site if location else None)
    book = read.book_at(location, day) if location and day else []
    lines = CountLineFormSet(prefix='lots', initial=[{'lot': lot.pk} for lot, _quantity in book])
    rows = FoundLotFormSet(prefix='found', initial=_posted_rows(data, 'found', FoundLotFormSet.form.base_fields))
    return render_page(request, 'inventory/count.html', {**context, 'form': form, 'lines': lines, 'rows': rows,
                                                         'location': location, 'pairs': _pairs(lines, book)})


def _location(value):
    if not _is_uuid(value or ''):
        return None
    return StorageLocation.objects.select_related('site').filter(pk=value).first()


def _posted_rows(data, prefix, names):
    """The rows of a list as the draft posted them, to show again (nothing validated)."""
    try:
        total = int(data.get(f'{prefix}-TOTAL_FORMS', 0))
    except ValueError:
        return []
    rows = [{name: data.get(f'{prefix}-{index}-{name}', '') for name in names} for index in range(min(total, 30))]
    return [row for row in rows if any(row.values())]


def _pairs(lines, book):
    """[(line form, lot, book quantity)]: each listed lot with what the book has of it there."""
    held = {str(lot.pk): (lot, quantity) for lot, quantity in book}
    ids = [str(line['lot'].value()) for line in lines.forms]
    lots = {str(pk): lot for pk, lot in InventoryLot.all_objects.select_related('item__feed').in_bulk(
        [pk for pk in ids if _is_uuid(pk)]).items()}
    return [(line, lots.get(pk), held.get(pk, (None, 0))[1]) for line, pk in zip(lines.forms, ids) if pk in lots]


@permission_required(VOID, raise_exception=True)
def void(request, pk):
    """Voids an operation, with the reason."""
    operation = get_object_or_404(InventoryOperation.objects.select_related('location', 'supplier'), pk=pk)
    lines = list(operation.lines.select_related('location', 'lot__item__feed'))
    back = _back(request)
    context = _context(operation=operation, lines=lines, heading=_('Void operation'), back_url=back)
    if request.method == 'POST':
        form = VoidForm(request.POST)
        if form.is_valid():
            try:
                services.void(request.user, operation, form.cleaned_data['reason'])
            except ValidationError as error:
                form.add_service_error(error)
            else:
                messages.success(request, _('%(operation)s of %(date)s voided.') % {
                    'operation': operation.get_kind_display(), 'date': shown_date(operation.date)})
                return done(request, back)
        return _refused(request, 'inventory/void.html', {**context, 'form': form})
    return render_page(request, 'inventory/void.html', {**context, 'form': VoidForm()})

"""Operations › Feeding records: the list of every feeding with its filters, and the dialogs to record
one (from a unit's drawer on Production units, or from the list) and to void one. The dialogs are the
stock's (farm/stock/views.py): the shared dialog or a page, the form posted to itself, the server's
reasons on their fields (422), and back to the page they were opened from.

Who may do what: reading the list needs view on the feeding records, recording one add, voiding one
delete (config/access.py); the buttons a person cannot use are not shown, and the views refuse them too."""
from datetime import date, timedelta
from urllib.parse import urlencode

from django.contrib import messages
from django.contrib.auth.decorators import permission_required
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.db.models import Count, Q, Sum
from django.shortcuts import get_object_or_404
from django.urls import reverse
from django.utils.translation import gettext as _, ngettext

from core import navigation
from core.crud import done, render_page

from ..forms.feeding import FeedingForm, feed_label
from ..forms.stock import VoidForm
from ..handling.fasting import fasting_on
from ..models import Batch, Feed, FeedingRecord, Site, Tank
from ..stock import read as stock_read, views as stock_views
from ..stock.dates import earliest, local_today, shown_date
from ..stock.services import AlreadyRecorded
from ..templatetags.feeding import amount
from ..templatetags.stock import grams, tonnes
from . import read, services

VIEW, RECORD, VOID = 'farm.view_feedingrecord', 'farm.add_feedingrecord', 'farm.delete_feedingrecord'
FILTERS = ('site', 'unit', 'batch', 'feed', 'from', 'to', 'voided')
PAGE_SIZE = 50
HISTORY = 10    # feedings listed in a unit's drawer


def _context(**extra):
    place = navigation.place(VIEW)
    return {'title': place.entry.label, 'eyebrow': f'{place.section.label} · {place.entry.label}', **extra}


def _back(request, unit=None):
    """Where a dialog goes back to: the page it was opened from (`next`, the list with its filters), else
    Production units with the unit's drawer open (the stock dialogs' rule)."""
    return stock_views._back(request, unit)


def _with_next(url, request):
    return f'{url}?{urlencode({"next": request.get_full_path()})}'


# ---- the list ------------------------------------------------------------------------------------
def _day(value):
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def _filtered(params):
    """The records the filters choose, voided ones only when asked for, newest first; and the filters'
    values that name something (a stale link shows everything, as the other pages do)."""
    records = FeedingRecord.all_objects.select_related(
        'unit__production_department__site', 'feed', 'feeder', 'created_by', 'deleted_by')
    if params['voided'] != '1':
        params['voided'] = ''
        records = records.filter(is_deleted=False)
    choices = {
        'site': Site.objects.filter(production_departments__tanks__feedings__isnull=False).distinct().order_by('name'),
        'unit': Tank.all_objects.filter(feedings__isnull=False).distinct().order_by('code'),
        'feed': Feed.all_objects.filter(feedings__isnull=False).distinct().order_by('name'),
        'batch': Batch.objects.order_by('-input_date', '-code'),
    }
    for key, lookup in (('site', 'unit__production_department__site'), ('unit', 'unit'), ('feed', 'feed')):
        if params[key] in {str(pk) for pk in choices[key].values_list('pk', flat=True)}:
            records = records.filter(**{lookup: params[key]})
        else:
            params[key] = ''
    for key, lookup in (('from', 'date__gte'), ('to', 'date__lte')):
        day = _day(params[key])
        params[key] = day.isoformat() if day else ''
        if day:
            records = records.filter(**{lookup: day})
    batch = choices['batch'].filter(pk=params['batch']).first() if stock_views._is_uuid(params['batch']) else None
    params['batch'] = str(batch.pk) if batch else ''
    if batch is not None:
        records = records.filter(pk__in=read.records_of_batch(batch, records))
    return records, choices


@permission_required(VIEW, raise_exception=True)
def feeding_records(request):
    params = {key: request.GET.get(key, '').strip() for key in FILTERS}
    records, choices = _filtered(params)
    totals = records.aggregate(count=Count('pk'), kilos=Sum('amount_kg', filter=Q(is_deleted=False)))
    page = Paginator(records, PAGE_SIZE).get_page(request.GET.get('page'))
    rows = list(page.object_list)
    split = read.split_of(rows)
    batches = Batch.all_objects.in_bulk({batch_id for parts in split.values() for batch_id in parts})
    can_void = request.user.has_perm(VOID)
    here = request.get_full_path()
    kept = {key: value for key, value in params.items() if value}
    return render_page(request, 'farm/feeding_list.html', _context(
        rows=[{
            'record': record,
            'batches': sorted((batches[batch_id] for batch_id in split.get(record.pk, {})), key=lambda b: b.code),
            'void_url': f'{reverse("farm:feeding_void", args=[record.pk])}?{urlencode({"next": here})}'
            if can_void and not record.is_deleted and record.date >= earliest(record.unit) else '',
        } for record in rows],
        page=page, pager_query=urlencode(kept), params=params, choices=choices,
        count_line=ngettext('%(count)d record', '%(count)d records', totals['count']) % {'count': totals['count']},
        kilos=totals['kilos'] or 0,
        filtered=bool({key for key in kept if key != 'voided'}),
        clear_url=reverse('farm:feeding_records'),
        record_url=_with_next(reverse('farm:feeding_new'), request) if request.user.has_perm(RECORD) else '',
    ))


# ---- the dialogs ---------------------------------------------------------------------------------
@permission_required(RECORD, raise_exception=True)
def choose_unit(request):
    """Record feeding from the list: the units with fish, each opening its feeding dialog."""
    units = list(Tank.objects.select_related('production_department__site').order_by('code'))
    stock = stock_read.stock_of(units)
    target = request.GET.get('next', '')
    query = f'?{urlencode({"next": target})}' if target else ''
    return render_page(request, 'farm/feeding_choose.html', _context(
        heading=_('Record feeding'), back_url=_back(request),
        units=[{'unit': unit, 'stock': stock[unit.pk], 'url': reverse('farm:feeding_record', args=[unit.pk]) + query}
               for unit in units if unit.pk in stock]))


def _split(unit, day):
    """The batches a feeding of `unit` on `day` would feed and their parts in %, when there are several."""
    book = read.book_on(unit, day)
    weights = book.weights
    if len(weights) < 2:
        return None
    total = sum(weights.values())
    batches = Batch.all_objects.in_bulk(weights)
    return {'at_start': bool(book.start), 'day': day,
            'parts': sorted(((batches[batch_id].code, 100 * part / total) for batch_id, part in weights.items()),
                            key=lambda item: item[0])}


@permission_required(RECORD, raise_exception=True)
def record_feeding(request, pk):
    """Feed given to one unit: in the dialog of its drawer, or of the list's Record feeding."""
    unit = get_object_or_404(Tank.objects.select_related('production_department__site'), pk=pk)
    stock = stock_read.stock_of([unit]).get(unit.pk)
    back = _back(request, unit)
    context = _context(unit=unit, stock=stock, heading=_('Record feeding'), back_url=back)
    if request.method == 'POST':
        form = FeedingForm(request.POST, unit=unit, stock=stock)
        if form.is_valid():
            try:
                record = form.save(request.user)
            except AlreadyRecorded:
                return done(request, back)
            except ValidationError as error:
                form.add_service_error(error)
            else:
                messages.success(request, _('Feeding recorded: %(kilos)s kg of %(feed)s in %(unit)s on %(date)s.') % {
                    'kilos': amount(record.amount_kg), 'feed': feed_label(record.feed), 'unit': unit.code,
                    'date': shown_date(record.date)})
                if form.suiting and record.feed.pk not in form.suiting:
                    # A feed among "Other active feeds" while some suit these fish: a notice, not a refusal.
                    messages.warning(request, _(
                        '%(feed)s is not listed as suitable for %(species)s at %(weight)s (Reference data › Feeds).')
                        % {'feed': record.feed, 'species': stock.batches[0].species,
                           'weight': grams(stock.avg_weight_g)})
                return done(request, back)
        day = form.cleaned_data.get('date') or local_today(unit)
        return stock_views._refused(request, 'farm/feeding_form.html', {
            **context, 'form': form, 'split': _split(unit, day), 'fasting': fasting_on(unit, day)})
    form = FeedingForm(unit=unit, stock=stock)
    return render_page(request, 'farm/feeding_form.html', {
        **context, 'form': form, 'split': _split(unit, local_today(unit)),
        'fasting': fasting_on(unit, local_today(unit))})


@permission_required(VOID, raise_exception=True)
def void_feeding(request, pk):
    """Voids a feeding, with the reason."""
    record = get_object_or_404(FeedingRecord.objects.select_related('unit__production_department__site', 'feed'),
                               pk=pk)
    back = _back(request, record.unit)
    context = _context(record=record, heading=_('Void feeding'), back_url=back)
    if request.method == 'POST':
        form = VoidForm(request.POST)
        if form.is_valid():
            try:
                services.void_feeding(request.user, record, form.cleaned_data['reason'])
            except ValidationError as error:
                form.add_service_error(error)
            else:
                messages.success(request, _('Feeding of %(date)s in %(unit)s voided.') % {
                    'date': shown_date(record.date), 'unit': record.unit.code})
                return done(request, back)
        return stock_views._refused(request, 'farm/feeding_void.html', {**context, 'form': form})
    return render_page(request, 'farm/feeding_void.html', {**context, 'form': VoidForm()})


# ---- what other pages show -----------------------------------------------------------------------
def drawer(request, unit, stock, feeding, query):
    """The Feeding part of a unit's drawer on Production units: its figures (`feeding`, read.figures), its
    last feedings, voided ones struck through, each with Void while it may be voided."""
    if not request.user.has_perm(VIEW):
        return {}
    can_void = request.user.has_perm(VOID)
    first = earliest(unit)
    recent = (FeedingRecord.all_objects.filter(unit=unit).select_related('feed', 'feeder', 'created_by', 'deleted_by')
              [:HISTORY])
    return {
        'feedings': [{'record': record,
                      'void_url': reverse('farm:feeding_void', args=[record.pk]) + query
                      if can_void and not record.is_deleted and record.date >= first else ''}
                     for record in recent],
        'feeding_list_url': f'{reverse("farm:feeding_records")}?{urlencode({"unit": unit.pk})}',
        'weighed_days': (feeding.today - stock.last_weighed).days if feeding and stock.last_weighed else None,
    }


def overview_tiles(user):
    """The production overview's feed figures: fed today and over the last 7 days on the whole farm (the
    company's today), for people who may read the feeding records."""
    if not user.has_perm(VIEW):
        return []
    today = local_today()
    first = today - timedelta(days=read.WEEK - 1)
    kilos = FeedingRecord.objects.filter(date__range=(first, today)).aggregate(
        today=Sum('amount_kg', filter=Q(date=today)), week=Sum('amount_kg'))
    url = reverse('farm:feeding_records')
    return [
        {'label': _('Feed today'), 'count': tonnes(kilos['today'] or 0),
         'url': f'{url}?{urlencode({"from": today.isoformat(), "to": today.isoformat()})}'},
        {'label': _('Feed, last 7 days'), 'count': tonnes(kilos['week'] or 0),
         'url': f'{url}?{urlencode({"from": first.isoformat(), "to": today.isoformat()})}'},
    ]


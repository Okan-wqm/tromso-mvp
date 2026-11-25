"""Operations › Feeding: the Meal board (today's ration and meals per unit with fish), Records (every feeding
with its filters, and by unit and day the calculated ration against the feed given), and the dialogs to record
a feeding (from a unit's drawer on Production units, from Records, or a meal from the board) and to void one. The
dialogs are the stock's (farm/stock/views.py): the shared dialog or a page, the form posted to itself, the
server's reasons on their fields (422), and back to the page they were opened from. The rations are computed on
read (farm/feeding/ration.py, projection.py), nothing about them is stored.

Who may do what: reading the board and Records needs view on the feeding records, recording one add, voiding one
delete (config/access.py); the buttons a person cannot use are not shown, and the views refuse them too."""
from datetime import time, timedelta
from decimal import ROUND_HALF_UP, Decimal
from urllib.parse import urlencode

from django.contrib import messages
from django.contrib.auth.decorators import permission_required
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.db.models import Count
from django.shortcuts import get_object_or_404
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import gettext as _, ngettext

from core import navigation
from core.crud import done, render_page
from core.dates import read_day
from core.ui import is_next

from .. import placements
from ..clocks import clocks, own_days
from ..forms.feeding import FeedingForm, feed_label
from ..forms.stock import VoidForm
from ..handling.fasting import fasting_on
from ..health import withdrawal as health_withdrawal
from ..models import Batch, Feed, FeedingRecord, Site, Tank
from ..models.feeding import FeedTarget
from ..models.site import zone_of
from ..stock import read as stock_read, views as stock_views
from ..stock.dates import earliest, local_today, shown_date
from ..stock.services import AlreadyRecorded
from ..templatetags.feeding import amount
from ..templatetags.stock import grams, tonnes
from . import pages, read, services

VIEW, RECORD, VOID = services.VIEW, services.RECORD, services.VOID
RECORDS, BOARD = 'farm:feeding_records', 'farm:meal_board'
FILTERS = ('site', 'unit', 'batch', 'feed', 'from', 'to', 'voided')
DAY_FILTERS = ('site', 'unit', 'batch', 'from', 'to')
DAYS, LIST = 'days', ''
PAGE_SIZE = 50
HISTORY = 10    # feedings listed in a unit's drawer
SPAN = 31       # the days one page of Records by unit and day covers at most
GRAM = Decimal('0.001')


def _context(url_name=RECORDS, **extra):
    """The page's title, the menu entry's label, and above it where the entry sits (Operations · Feeding)."""
    place = navigation.page(url_name)
    eyebrow = ' · '.join(str(label) for label in (place.section.label, place.group.label) if label)
    return {'title': place.entry.label, 'eyebrow': eyebrow, **extra}


def _page(request, template, context, props):
    """The classic page, or in the new look (core.ui.is_next) the shared list page with the props of farm/feeding/pages.py
    (`props`: their builder, given the request and the classic page's context)."""
    if is_next(request):
        return render_page(request, 'crud/list_next.html', {**context, 'group': context['eyebrow'],
                                                            'props': props(request, context)})
    return render_page(request, template, context)


def _back(request, unit=None):
    """Where a dialog goes back to: the page it was opened from (`next`, the list with its filters), else
    Production units with the unit's drawer open (the stock dialogs' rule)."""
    return stock_views._back(request, unit)


def _with_next(url, request):
    return f'{url}?{urlencode({"next": request.get_full_path()})}'


# ---- the list ------------------------------------------------------------------------------------
def _filtered(params, request):
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
        day = read_day(params[key], request)
        params[key] = day or ''          # a date: the input shows it as the language writes it
        if day:
            records = records.filter(**{lookup: day})
    batch = choices['batch'].filter(pk=params['batch']).first() if stock_views._is_uuid(params['batch']) else None
    params['batch'] = str(batch.pk) if batch else ''
    if batch is not None:
        records = records.filter(pk__in=read.records_of_batch(batch, records))
    return records, choices


@permission_required(VIEW, raise_exception=True)
def feeding_records(request):
    """Records: the feeding records (the list), or by unit and day the calculated ration and the feed given."""
    if request.GET.get('view') == DAYS:
        return _by_day(request)
    params = {key: request.GET.get(key, '').strip() for key in FILTERS}
    records, choices = _filtered(params, request)
    totals = records.aggregate(count=Count('pk'), kilos=read.given())
    page = Paginator(records, PAGE_SIZE).get_page(request.GET.get('page'))
    rows = list(page.object_list)
    split = read.split_of(rows)
    batches = Batch.all_objects.in_bulk({batch_id for parts in split.values() for batch_id in parts})
    can_void = request.user.has_perm(VOID)
    here = request.get_full_path()
    kept = {key: value for key, value in params.items() if value}
    return _page(request, 'farm/feeding_list.html', _context(
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
        clear_url=reverse('farm:feeding_records'), views=_views(request, LIST),
        record_url=_with_next(reverse('farm:feeding_new'), request) if request.user.has_perm(RECORD) else '',
    ), pages.records_props)


def _views(request, current):
    """The two views of Records, each keeping the filters they share."""
    shared = {key: request.GET.get(key, '') for key in DAY_FILTERS if request.GET.get(key)}
    url = reverse(RECORDS)
    return [{'label': _('Feeding records'), 'url': f'{url}?{urlencode(shared)}' if shared else url,
             'current': current == LIST},
            {'label': _('By unit and day'), 'url': f'{url}?{urlencode({"view": DAYS, **shared})}',
             'current': current == DAYS}]


def _by_day(request):
    """By unit and day: the calculated ration (farm/feeding/projection.py: the meals recorded at the estimate before
    each, the meals to come at the estimate now) against the feed given, the deviation, and the weighings'
    corrections. At most SPAN days a page, the last 7 by default; computed on read in one walk."""
    params = {key: request.GET.get(key, '').strip() for key in DAY_FILTERS}
    today = local_today()
    last = min(read_day(params['to'], request) or today, today)
    first = min(read_day(params['from'], request) or last - timedelta(days=read.WEEK - 1), last)
    clipped = (last - first).days >= SPAN
    if clipped:
        first = last - timedelta(days=SPAN - 1)
    params['from'], params['to'] = first, last              # dates: an input shows them as the language writes them
    units = list(Tank.objects.select_related('production_department__site').order_by('code'))
    choices = {'site': sorted({unit.production_department.site for unit in units if unit.production_department.site},
                              key=lambda site: site.name),
               'unit': units, 'batch': Batch.objects.order_by('-input_date', '-code')}
    if params['site'] in {str(site.pk) for site in choices['site']}:
        units = [unit for unit in units if str(unit.production_department.site_id) == params['site']]
    else:
        params['site'] = ''
    if params['unit'] in {str(unit.pk) for unit in units}:
        units = [unit for unit in units if str(unit.pk) == params['unit']]
    else:
        params['unit'] = ''
    batch = choices['batch'].filter(pk=params['batch']).first() if stock_views._is_uuid(params['batch']) else None
    params['batch'] = str(batch.pk) if batch else ''
    if batch is not None:
        visited = set(batch.movements.filter(operation__is_deleted=False).values_list('unit_id', flat=True))
        units = [unit for unit in units if unit.pk in visited]
    span = [first + timedelta(days=n) for n in range((last - first).days + 1)]
    projection = None
    if units:
        projection = read.project([unit.pk for unit in units], [(unit.pk, day) for unit in units for day in span])
    # What the production fish were given is what the calculated ration and the deviation are about; the cleaner fish's
    # feed has a line of its own beside it, never in the sum.
    given, cleaner = {}, {}
    for row in (FeedingRecord.objects.filter(unit__in=units, date__range=(first, last))
                .values('unit_id', 'date', 'target').annotate(kilos=read.given())):
        (cleaner if row['target'] == FeedTarget.CLEANER_FISH else given)[(row['unit_id'], row['date'])] = row['kilos']
    by_id = {unit.pk: unit for unit in units}
    unit_days = projection.days if projection else {}
    corrections = {}
    for unit in units:
        for correction in projection.corrections(unit.pk) if projection else []:
            corrections.setdefault((unit.pk, correction.day), []).append(correction)
    batches = Batch.all_objects.select_related('species').in_bulk(
        {share.batch_id for unit_day in unit_days.values() for share in unit_day.shares}
        | {correction.batch_id for found in corrections.values() for correction in found})
    rows = []
    for unit_id, day in sorted(set(given) | set(cleaner) | set(unit_days),
                               key=lambda key: (-key[1].toordinal(), by_id[key[0]].code)):
        unit_day = unit_days.get((unit_id, day))
        shares = unit_day.shares if unit_day else []
        if batch is not None and batch.pk not in {share.batch_id for share in shares}:
            continue
        rows.append({
            'unit': by_id[unit_id], 'day': day, 'unit_day': unit_day, 'given_kg': given.get((unit_id, day), 0),
            'cleaner_kg': cleaner.get((unit_id, day), 0),
            'shares': [{'share': share, 'batch': batches[share.batch_id],
                        'why': share.end.why(batches[share.batch_id])} for share in shares],
            'corrections': [{'correction': correction, 'batch': batches[correction.batch_id]}
                            for correction in corrections.get((unit_id, day), [])]})
    page = Paginator(rows, PAGE_SIZE).get_page(request.GET.get('page'))
    kept = {key: value for key, value in params.items() if value}
    calculated = [row['unit_day'].calculated_kg for row in rows if row['unit_day'] is not None]
    return _page(request, 'farm/feeding_list.html', _context(
        view=DAYS, views=_views(request, DAYS), day_rows=page.object_list, page=page,
        pager_query=urlencode({'view': DAYS, **kept}), params=params, choices=choices, clipped=clipped, span=SPAN,
        given_kg=sum((row['given_kg'] for row in rows), 0), cleaner_kg=sum((row['cleaner_kg'] for row in rows), 0),
        calculated_kg=sum(calculated) if calculated and None not in calculated else None,
        filtered=bool(set(kept) - {'from', 'to'}), clear_url=f'{reverse(RECORDS)}?view={DAYS}',
        record_url=_with_next(reverse('farm:feeding_new'), request) if request.user.has_perm(RECORD) else ''),
        pages.days_props)


# ---- the meal board --------------------------------------------------------------------------------
BOARD_FILTERS = ('site', 'department', 'system')


def _attribute(item, dotted):
    for name in dotted.split('.'):
        item = getattr(item, name)
    return item


@permission_required(VIEW, raise_exception=True)
def meal_board(request):
    """Today on the farm's clock, per unit with fish: the fish, their measured and estimated weight, the temperature,
    the protocol that applies and why, the band, SFR, ration and meals, the feed and pellet, what was fed today, what
    remains and the next meal, with Record meal. A unit whose ration cannot be computed says why."""
    params = {key: request.GET.get(key, '').strip() for key in BOARD_FILTERS}
    units = list(Tank.objects.select_related('production_department__site', 'system').order_by('code'))
    stock = stock_read.stock_of(units)
    stocked = [unit for unit in units if unit.pk in stock]
    choices = {
        'site': sorted({unit.production_department.site for unit in stocked if unit.production_department.site},
                       key=lambda site: site.name),
        'department': sorted({unit.production_department for unit in stocked}, key=lambda item: item.name),
        'system': sorted({unit.system for unit in stocked if unit.system}, key=lambda system: system.name),
    }
    for key, attribute in (('site', 'production_department.site_id'), ('department', 'production_department_id'),
                           ('system', 'system_id')):
        if params[key] in {str(item.pk) for item in choices[key]}:
            stocked = [unit for unit in stocked if str(_attribute(unit, attribute)) == params[key]]
        else:
            params[key] = ''
    today = {unit.pk: local_today(unit) for unit in stocked}
    chips = placements.of(stocked, request.user)
    projection = None
    if stocked:
        projection = read.project([unit.pk for unit in stocked], [(unit.pk, today[unit.pk]) for unit in stocked])
    can_record, can_sample, here = (request.user.has_perm(RECORD), request.user.has_perm('farm.add_watermeasurement'),
                                    request.get_full_path())
    rows = []
    for unit in stocked:
        unit_day = projection.days.get((unit.pk, today[unit.pk]))
        batches = {share.batch.pk: share.batch for share in stock[unit.pk].shares}
        lines = read.meal_lines(unit_day, batches, today[unit.pk])
        temperature = next((line['share'].end.temperature for line in lines if line['share'].end.temperature), None)
        # The chip compares the weights the lines show: the estimate where feed was credited since the measured point.
        factors = {line['share'].batch_id: line['share'].end_g / line['share'].measured_g for line in lines
                   if line['share'].fed_since_kg > 0 and line['share'].measured_g}
        rows.append({
            'unit': unit, 'stock': stock[unit.pk], 'day': unit_day, 'lines': lines, 'temperature': temperature,
            'mixes': stock[unit.pk].size_mixes_at(factors),
            'placements': chips.get(unit.pk, ()),
            'record_url': f'{reverse("farm:feeding_record", args=[unit.pk])}?'
                          f'{urlencode({"meal": "next", "next": here})}' if can_record else '',
            'water_url': f'{reverse("farm:water_record")}?{urlencode({"unit": unit.pk})}' if can_sample else ''})
    return _page(request, 'farm/meal_board.html', _context(
        BOARD, rows=rows, params=params, choices=choices, filtered=any(params.values()), clear_url=reverse(BOARD)),
        pages.meal_board_props)


def next_meal(unit):
    """What Record meal fills in: the next meal's kilos (at the estimate now), one meal, the band's feed when the
    unit's batches eat one, and now on the clock of the unit's site; None when there is no next meal."""
    today = local_today(unit)
    unit_day = read.project([unit.pk], [(unit.pk, today)]).days.get((unit.pk, today))
    if unit_day is None or unit_day.next_meal_kg is None:
        return None
    feeds = {share.end.band.feed for share in unit_day.production if share.next_meal_kg is not None}
    now = timezone.localtime(timezone.now(), zone_of(unit.production_department.site))
    return {'amount_kg': unit_day.next_meal_kg.quantize(GRAM, ROUND_HALF_UP), 'meals': 1,
            'time': time(now.hour, now.minute),
            'feed': feeds.pop() if len(feeds) == 1 else None}


# ---- the dialogs ---------------------------------------------------------------------------------
@permission_required(RECORD, raise_exception=True)
def choose_unit(request):
    """Record feeding from the list: the units with fish, and those whose fish left on a day that may still be dated
    (a feeding of such a day can still be entered, flow fault S-04), each opening its feeding dialog."""
    units = list(Tank.objects.select_related('production_department__site').order_by('code'))
    stock = stock_read.stock_of(units)
    left = stock_read.left_within([unit for unit in units if unit.pk not in stock], earliest)
    target = request.GET.get('next', '')
    query = f'?{urlencode({"next": target})}' if target else ''
    return render_page(request, 'farm/feeding_choose.html', _context(
        heading=_('Record feeding'), back_url=_back(request),
        units=[{'unit': unit, 'stock': stock.get(unit.pk), 'left': left.get(unit.pk),
                'url': reverse('farm:feeding_record', args=[unit.pk]) + query}
               for unit in units if unit.pk in stock or unit.pk in left]))


def _split(unit, day, target=FeedTarget.PRODUCTION):
    """The batches a feeding of `unit` on `day` for `target` would feed and their parts in %, when there are
    several."""
    book = read.book_on(unit, day).of(target)
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
                suiting = form.suiting_for.get(record.target)
                if suiting and record.feed.pk not in suiting:
                    # A feed among "Other active feeds" while some suit these fish: a notice, not a refusal.
                    messages.warning(request, _(
                        '%(feed)s is not listed as suitable for %(species)s at %(weight)s (Reference data › Feeds).')
                        % {'feed': record.feed, 'species': form.species_for[record.target],
                           'weight': grams(stock.of(record.target).avg_weight_g)})
                if record.feed.feed_type == Feed.Type.MEDICATED and not health_withdrawal.covered(record):
                    # Medicated feed holds the fish with an unknown withdrawal until its treatment is recorded.
                    messages.warning(request, _('No in-feed treatment covers this day: record it under Health › '
                                                'Treatments, or the fish’s withdrawal stays unknown.'))
                return done(request, back)
        day = form.cleaned_data.get('date') or local_today(unit)
        return stock_views._refused(request, 'farm/feeding_form.html', {
            **context, 'form': form, 'split': _split(unit, day, form.fed_to), 'fasting': fasting_on(unit, day)})
    form = FeedingForm(unit=unit, stock=stock)
    meal = next_meal(unit) if request.GET.get('meal') == 'next' else None
    if meal is not None:
        # Record meal on the board: the next meal filled in; the feed only while it is active.
        feed = meal['feed']
        form.initial.update({'amount_kg': meal['amount_kg'], 'meals': meal['meals'], 'time': meal['time'],
                             **({'feed': feed.pk} if feed is not None and feed.status == Feed.Status.ACTIVE else {})})
    return render_page(request, 'farm/feeding_form.html',
                       {**context, 'form': form, 'meal': meal, 'split': _split(unit, local_today(unit)),
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
                services.void_feeding(request.user, record, form.cleaned_data['reason'],
                                      withdrawal_ack=form.cleaned_data['withdrawal_ack'])
            except ValidationError as error:
                form.add_service_error(error)
            else:
                messages.success(request, _('Feeding of %(date)s in %(unit)s voided.') % {
                    'date': shown_date(record.date), 'unit': record.unit.code})
                return done(request, back)
        return stock_views._refused(request, 'farm/feeding_void.html', {**context, 'form': form})
    return render_page(request, 'farm/feeding_void.html', {**context, 'form': VoidForm()})


# ---- what other pages show -----------------------------------------------------------------------
def unit_figures(user, stock, **kwargs):
    """The feeding figures of the units with fish on Production units (FCR, last fed, the drawer's week and
    ration; read.figures, whose keywords it passes on), by unit id; nothing for a person who may not read the
    feeding records. The twin of water.views.unit_water."""
    if not user.has_perm(VIEW):
        return {}
    return read.figures(stock, **kwargs)


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
    """The production overview's feed figures: fed today and over the last 7 days on the whole farm, **each site on its
    own day** (the owner's decision of 12.11.2026; farm.clocks.own_days). Feed recorded on a site's today is in "Feed
    today" at once, whatever the company's clock says; the 7 days are each site's own last 7; a figure over sites on
    different clocks is the sum of each site's own day, and the cards of a farm with more than one clock say so
    (`sub`). Each card opens the records of its days, from the earliest to the latest among the sites (on a farm whose
    sites are on different days just then, that list holds a day more of one site than the figure). For people who may
    read the feeding records.

    **A unit whose department has no site** (a row a deleted site left, farm 0029) reads the company's day everywhere
    (`local_today`), and so here: the company's clock is one of the clocks counted. **One query, bounded**: the sums
    have their own days in FILTER clauses, and the query reads only the records of the days some clock counts, from
    the first of the earliest clock's seven days to the latest clock's today, never the whole table."""
    if not user.has_perm(VIEW):
        return []
    now = clocks()                                         # the sites' clocks, and the company's for a unit with no site
    site = 'unit__production_department__site'
    todays = [clock.today for clock in now]
    kilos = FeedingRecord.objects.filter(
        date__range=(min(todays) - timedelta(days=read.WEEK - 1), max(todays)),
    ).aggregate(today=read.given(own_days(now, site)), week=read.given(own_days(now, site, read.WEEK)))
    days = [clock.today for clock in now if clock.sites is not None] or todays       # the cards open the sites' days
    earliest_day, latest_day = min(days), max(days)
    first = earliest_day - timedelta(days=read.WEEK - 1)
    sub = _('Each site on its own day') if len({clock.zone for clock in now if clock.sites is not None}) > 1 else ''
    url = reverse('farm:feeding_records')
    return [
        {'key': 'today', 'label': _('Feed today'), 'count': tonnes(kilos['today'] or 0), 'sub': sub,
         'url': f'{url}?{urlencode({"from": earliest_day.isoformat(), "to": latest_day.isoformat()})}'},
        {'key': 'week', 'label': _('Feed, last 7 days'), 'count': tonnes(kilos['week'] or 0), 'sub': sub,
         'url': f'{url}?{urlencode({"from": first.isoformat(), "to": latest_day.isoformat()})}'},
    ]


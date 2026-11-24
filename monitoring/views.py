"""Operations › Monitoring: the wall. The page (`monitor`) is the toolbar and a grid of cards, one per tank, pond or cage,
simple or detailed; the fragment (`cards`) is the grid's children, which the browser asks for again (frontend/poll.ts)
and which the server answers without a body while nothing has changed. The page is drawn first without its cards (the
shell: "Loading the cards…") and the grid's first poll brings them; `?full=1` draws them in the page, as without
script. The cards are composed by monitoring/read.py from the other modules' own reads; nothing is stored or written
here, a poll included, except that a wall (`?wall=1`) keeps its session alive once a day.

Who may read it: the right to read stock operations (the page's gate, as Production units); each section of a card needs
its own right (monitoring/read.py `sections_for`) and the card says so for one the person may not read. The fragment has
the same gate. The Deffeyes chart in a card's window is the water page's endpoint (farm:water_unit_chart), which needs
the right to read water samples."""
import json
from types import SimpleNamespace
from urllib.parse import urlencode
from uuid import UUID

from django.conf import settings
from django.contrib.auth.decorators import permission_required
from django.db import transaction
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import gettext as _, gettext_lazy, ngettext, pgettext
from django.views.decorators.http import require_POST

from core import audit, navigation, ui
from core.dates import company_today, company_zone
from core.crud import render_page
from farm.models import ProductionDepartment, Site, System, Tank
from farm.stock.views import VIEW

from . import read
from .cards import builtin, catalogue, resolve, validate
from .models import CardTemplate, CardWidth, MonitorBoard

POLL = 'monitoring:cards'
PANE = 'monitoring:pane'
SESSION_DAY = 'monitoring_wall_day'


def _context(**extra):
    place = navigation.page('monitoring:monitor')
    return {'title': place.entry.label, 'eyebrow': f'{place.section.label} · {place.entry.label}', **extra}


def _keep_alive(request, params):
    """A wall page and its polls extend their session once a day: the default session is two weeks, and a wall that
    signs itself out freezes. The only write on this path, a session row, at most once a day (owner decision)."""
    if not params.wall:
        return
    today = company_today().isoformat()
    if request.session.get(SESSION_DAY) != today:
        request.session[SESSION_DAY] = today      # modifying the session saves it with a new expiry


def _look(request):
    """The look the cards are drawn in (core/ui.py): 'next' for the new look, '' for the classic one. The fragments are rendered
    without a request, so their context carries it (UI_NEXT, as the context processor names it for a page), and the
    change tokens hold it: a screen that changes its look never keeps the other look's cards behind a 204."""
    return ui.NEXT if ui.is_next(request) else ''


def _poll_url(query, token, name=POLL):
    return f'{reverse(name)}?{query}{"&" if query else ""}{urlencode({"after": token})}'


def _board(params):
    """The board the address names, with its rows; None for none or a stale link (the page then shows what it can)."""
    if not params.board:
        return None
    return MonitorBoard.objects.prefetch_related('rows').filter(pk=params.board).first()


def _unavailable():
    """A source the cards' state needs could not be read: 503, so a polling screen backs off and keeps its last
    picture with its stale notice (frontend/poll.ts), and a page says so rather than draw a guess."""
    return HttpResponse(_('The cards cannot be read just now. The screen keeps its last picture; try again shortly.'),
                        status=503, headers={'Cache-Control': 'no-store', 'Retry-After': '30'},
                        content_type='text/plain; charset=utf-8')


def _grid(request, params, board, now=None):
    """The context of the grid: the cards after the filters and the occupancy, how many units are not shown, the band
    above them (the tally per state and the chips of what needs a look) and the switch of the page's cards."""
    units = read.units_for(params, board)
    found = read.cards(units, request.user, resolve.Choice.of(board, params), params.occupancy, now)
    farm = Tank.objects.count()
    band = read.band(found)
    # (review R2) critical units no chip has room for: a wall of exactly those, one click from the band
    hidden = params.canonical(units=tuple(str(card.unit.pk) for card in band.hidden), flip=frozenset(), focus='')
    openers = _openers(params, found)
    return {
        'band_hidden_url': f'{reverse("monitoring:monitor")}?{hidden}' if band.hidden else '',
        'rows': [{'card': card, 'flip': _flip_urls(params, card), 'zoom': _zoom_urls(params, card),
                  'open': openers.get(card.unit.pk)} for card in found],
        'openers': openers,
        'band': band, 'modes': _modes(params, board), 'chart_views': _chart_views(params, found),
        'params': params, 'card_width': board.card_width if board is not None else CardWidth.AUTO,
        'UI_NEXT': bool(_look(request)),
        'computed_at': timezone.make_naive(now, company_zone()),     # naive: a template shows an aware one in UTC
        'shown': len(found), 'on_farm': farm,
        'count_line': ngettext('%(shown)d of %(farm)d unit shown', '%(shown)d of %(farm)d units shown', farm)
        % {'shown': len(found), 'farm': farm},
    }


# How a screen's cards can be drawn, as the toolbar's choice and the band's switch name them. Small is a VIEW: every
# card of the screen, whatever the rules and the board say (monitoring/cards/resolve.py). Without a board, '' is the
# farm's own rules (Simple where it has made none) and Detailed the page's choice below them; on a board, '' is the
# board's own cards.
MODE_CHOICES = ((read.SMALL, gettext_lazy('Small')), (read.BIG, gettext_lazy('Big')), ('', gettext_lazy('Simple')),
                (read.DETAILED, gettext_lazy('Detailed')))
BOARD_CHOICES = ((read.SMALL, gettext_lazy('Small')), (read.BIG, gettext_lazy('Big')), ('', gettext_lazy('As the board')))
# The two views of a chart's picture, as the band's and a card's switch name them (owner decision 12).
CHART_CHOICES = (('', gettext_lazy('Close-up')), (read.CHART_FULL, gettext_lazy('Full scale')))


def _modes(params, board):
    """The band's switch of the screen's cards: [{label, url, current, id}], each the page drawn with that kind of card
    and no card flipped (and, for the full-height cards, no pane beside them: the pane is the way into ONE tank from
    an overview). Plain links: they work without script, and a wall, which has no toolbar, changes its cards with
    them. Each has an id, so a poll that replaces the band gives the focus back (review R8)."""
    page = reverse('monitoring:monitor')
    on_board = board is not None
    chosen = params.mode if params.mode in (read.SMALL, read.BIG) or (not on_board and params.mode == read.DETAILED) else ''
    found = []
    for key, label in (BOARD_CHOICES if on_board else MODE_CHOICES):
        query = params.canonical(mode=key, flip=frozenset(), focus='' if key == read.BIG else params.focus)
        found.append({'label': label, 'url': f'{page}?{query}' if query else page, 'current': key == chosen,
                      'id': key or ('board' if on_board else 'simple')})
    return found


def _address(query, name='monitoring:monitor'):
    return f'{reverse(name)}?{query}' if query else reverse(name)


def _chart_views(params, found):
    """The band's switch of the screen's charts, when a card of the screen draws one: [{label, url, poll, current}],
    each the page with every chart in that view and no card differing. Links, as the cards' switch."""
    if not any(view.type == 'chart' for card in found for view in card.widgets):
        return []
    return [{'label': label, 'current': key == params.chart, 'id': key or 'close',
             'url': _address(params.canonical(chart=key, zoom=frozenset())),
             'poll': _address(params.canonical(chart=key, zoom=frozenset()), POLL)} for key, label in CHART_CHOICES]


def _zoom_urls(params, card, poll=POLL):
    """A card's own switch of its chart's view: [{label, url, poll, current}]. The address keeps the cards that
    differ from the screen's view (`zoom`), as it keeps the flipped ones. `poll`: the fragment the card is part of
    (the grid's, or the pane's for the card in the pane)."""
    unit, found = str(card.unit.pk), []
    differs = unit in params.zoom
    for key, label in CHART_CHOICES:
        current = (key == params.chart) != differs
        zoom = params.zoom if current else params.zoom ^ {unit}
        query = params.canonical(zoom=frozenset(zoom))
        found.append({'label': label, 'current': current, 'url': _address(query), 'poll': _address(query, poll)})
    return found


def _openers(params, found):
    """{unit id: {page, open}} for the cards that are the way INTO their tank (owner decision 7: from a small card the
    operator opens that tank's Big card): the fitted cards that are not full-height ones themselves. `page`: the
    address with that unit in the pane, or, for the unit that is in it, the address with the pane closed; `open`:
    whether it is the one. A link: it works without script (frontend/windows.ts docks the pane without a page load)."""
    openers = {}
    for card in found:
        if not card.template.measure or card.template.fill:
            continue
        unit = str(card.unit.pk)
        is_open = unit == params.focus
        openers[card.unit.pk] = {'page': _address(params.canonical(focus='' if is_open else unit)), 'open': is_open,
                                 'into': _address(params.canonical(focus=unit))}
    return openers


def _pane(request, params, now=None):
    """The context of the pane (monitoring/_pane.html): the Big card of the unit the address has gone into, read as any
    card is (the same read, the person's own rights, the screen's chart view), or None when the address names no unit
    or one that is gone. One unit's read: what it costs does not depend on the wall beside it."""
    if not params.focus:
        return None
    unit = Tank.objects.select_related('production_department__site', 'system').filter(pk=params.focus).first()
    if unit is None:
        return None
    choice = resolve.Choice(view=builtin.BIG, chart=params.chart, zoom=params.zoom)
    found = read.cards([unit], request.user, choice, read.ALL, now)
    if not found:
        return None
    card = found[0]
    return {'row': {'card': card, 'flip': {}, 'zoom': _zoom_urls(params, card, PANE), 'pane': True, 'ns': 'pane-'},
            'pane_unit': unit, 'close_url': _address(params.canonical(focus='')), 'UI_NEXT': bool(_look(request))}


def _pane_token(request, params, revision=None):
    return read.change_token(request.user, f'pane?{params.canonical()}', board=params.board, revision=revision,
                             look=_look(request))


def _flip_urls(params, card):
    """The Simple/Detailed link of a card: the page with this card flipped (what the address keeps), and the fragment's
    address for that state (data-poll-url: with the script the grid refetches, without it the link navigates)."""
    flip = set(params.flip)
    flip ^= {str(card.unit.pk)}
    changed = params.canonical(flip=frozenset(flip))
    return {'page': f'{reverse("monitoring:monitor")}?{changed}' if changed else reverse('monitoring:monitor'),
            'poll': f'{reverse(POLL)}?{changed}' if changed else reverse(POLL)}


def _page(params, board, /, **extra):
    """The context of the page around the grid, the same for the shell and the full page: the toolbar's lists, the
    windows' place, the polls' interval and the page's own addresses. `extra`: what the caller adds (the grid's context,
    the polls' addresses, the pane)."""
    return _context(**{
        'query': params.canonical(), 'board': board, 'params': params, 'big_measure': builtin.BIG_MEASURE,
        'boards': MonitorBoard.objects.order_by('name'),
        'poll_seconds': board.seconds if board else settings.MONITOR_POLL_SECONDS,
        'wall': params.wall, 'windows_key': params.board or 'adhoc',
        'wall_url': f'{reverse("monitoring:monitor")}?{params.canonical(wall=True)}',
        'page_url': _address(params.canonical(wall=False)),
        'sites': Site.objects.order_by('name'), 'departments': ProductionDepartment.objects.order_by('name'),
        'systems': System.objects.order_by('name'), 'all_units': Tank.objects.order_by('code'),
        'kinds': [(Tank.Kind.TANK, _('Tanks')), (Tank.Kind.POND, _('Ponds')), (Tank.Kind.CAGE, _('Cages'))],
        'occupancies': [(read.STOCKED, pgettext('occupancy', 'Stocked')), (read.EMPTY, _('Empty')), (read.ALL, _('All'))],
        **extra})


@permission_required(VIEW, raise_exception=True)
def monitor(request):
    """The page. By default the SHELL (shell-first, live-arch stage 1): the toolbar, the grid's place and the windows'
    place, with "Loading the cards…" where the cards go and no card, band, tally or state of any unit, so a page whose
    cards have not come never reads as all is well. It reads no card source: its cost does not depend on the farm. The
    grid's poll (frontend/poll.ts, data-poll-state="loading") asks for the fragment at once, at an address without a
    token, so its first answer is always the cards (200), never "nothing changed" (204); a failure there says the cards
    cannot be read (a 503) or that the person is signed out (401, 403). With a focus the pane's frame is drawn and its
    body filled the same way. `?full=1` is the page as it was before, the cards drawn by the server: the way in without
    script (the shell's <noscript> link)."""
    params = read.Params.from_query(request.GET)
    _keep_alive(request, params)
    if request.GET.get('full') == '1':
        return _full(request, params)
    board = _board(params)
    unit = Tank.objects.filter(pk=params.focus).first() if params.focus else None
    # (the unit's card comes with the pane's first poll; a unit that is gone has no pane, as on the full page)
    pane = {'pane_unit': unit, 'close_url': _address(params.canonical(focus=''))} if unit is not None else None
    full = '&'.join(part for part in (params.canonical(), 'full=1') if part)
    return render_page(request, 'monitoring/monitor.html', _page(
        params, board, shell=True, pane=pane, pane_poll_url=_address(params.canonical(), PANE),
        poll_url=_address(params.canonical(), POLL), full_url=f'{reverse("monitoring:monitor")}?{full}',
        card_width=board.card_width if board is not None else CardWidth.AUTO))


def _full(request, params):
    """The full page (`?full=1`): toolbar, grid with the cards, the windows' place. The token is read before the cards,
    so a change between the two shows at the first poll."""
    revision = audit.revision()                  # once, before any data, for both tokens
    token = read.change_token(request.user, params.canonical(), board=params.board, revision=revision,
                              look=_look(request))
    now = timezone.now()
    board = _board(params)
    pane_token = _pane_token(request, params, revision)
    try:
        grid = _grid(request, params, board, now)
        pane = _pane(request, params, now)
    except read.Unavailable:
        return _unavailable()
    return render_page(request, 'monitoring/monitor.html', _page(
        params, board, **grid, token=token, pane=pane, pane_poll_url=_poll_url(params.canonical(), pane_token, PANE),
        poll_url=_poll_url(params.canonical(), token)))


@permission_required(VIEW, raise_exception=True)
def cards(request):
    """The grid's children for the address: 204 with the same next address while nothing has changed since `after`,
    else 200 with the cards and the next address (X-Poll-Next) carrying the new token. No request goes to the
    template, so the shell's context (the menu, the unread count) is never worked out for a poll."""
    params = read.Params.from_query(request.GET)
    _keep_alive(request, params)
    query = params.canonical()
    token = read.change_token(request.user, query, board=params.board, look=_look(request))
    headers = {'Cache-Control': 'no-store', 'X-Poll-Next': _poll_url(query, token)}
    if request.GET.get('after') == token:
        return HttpResponse(status=204, headers=headers)
    now = timezone.now()
    try:
        grid = _grid(request, params, _board(params), now)
    except read.Unavailable:
        return _unavailable()
    html = render_to_string('monitoring/_grid.html', {**grid, 'wall': params.wall})
    return HttpResponse(html, headers=headers)


@permission_required(VIEW, raise_exception=True)
def pane(request):
    """The pane's content for the address: the Big card of the unit gone into (`focus`), keyed like a card of the grid
    so frontend/poll.ts merges it; 204 with the same next address while nothing has changed since `after`, as the
    grid's fragment; 404 when the address names no unit or one that is gone (the pane then closes: poll.ts `poll:gone`,
    frontend/windows.ts)."""
    params = read.Params.from_query(request.GET)
    _keep_alive(request, params)
    if not params.focus:
        return HttpResponse(status=404, headers={'Cache-Control': 'no-store'})
    token = _pane_token(request, params)
    headers = {'Cache-Control': 'no-store', 'X-Poll-Next': _poll_url(params.canonical(), token, PANE)}
    if request.GET.get('after') == token:
        return HttpResponse(status=204, headers=headers)
    try:
        found = _pane(request, params, timezone.now())
    except read.Unavailable:
        return _unavailable()
    if found is None:
        return HttpResponse(status=404, headers={'Cache-Control': 'no-store'})
    return HttpResponse(render_to_string('monitoring/_pane.html', found), headers=headers)


# ---- Reference data › Card templates --------------------------------------------------------------------------------
def _copy_name(source):
    """'<name> (copy)', or '(copy 2)', '(copy 3)' … while the name is taken by a live template (any case)."""
    base = source.shown_name
    names = {name.lower() for name in CardTemplate.objects.values_list('name', flat=True)}
    candidate, number = _('%(name)s (copy)') % {'name': base}, 2
    while candidate.lower() in names:
        candidate = _('%(name)s (copy %(number)d)') % {'name': base, 'number': number}
        number += 1
    return candidate


@require_POST
@permission_required('monitoring.add_cardtemplate', raise_exception=True)
def copy_template(request, pk):
    """A copy of a template (the way to change a built-in): its description, layout, measure and flip target, a name of
    its own; logged as a new record, then its form opens."""
    from .resources import CardTemplateResource
    source = get_object_or_404(CardTemplate, pk=pk)
    with transaction.atomic():
        copy = CardTemplate.objects.create(
            name=_copy_name(source), description=source.description, layout=source.layout,
            schema_version=source.schema_version, expanded=source.expanded, measure_w=source.measure_w,
            measure_h=source.measure_h, created_by=request.user,
            updated_by=request.user)
        audit.record_create(request.user, copy, CardTemplateResource.recorded(copy),
                            entity_type=CardTemplateResource.entity_type())
    return redirect('monitoring:cardtemplate_edit', pk=copy.pk)


PREVIEW_BYTES = 65536


@require_POST
@permission_required('monitoring.change_cardtemplate', raise_exception=True)
def preview(request):
    """The designer's preview: {layout, unit, name?, state?, measure?} as JSON; answers {html, problems}. The layout is
    checked by the validator first, with the measure the form has now ([width, height] in card units: a fitted
    template, whose card is drawn fitted; none: a card that flows): an error draws nothing, then the same card read
    and the same _card.html as the wall draw it for that one unit, with the previewer's own rights. Nothing is written
    and nothing is logged. `state` forces the frame's state for a look at it; it is accepted here only, and the card
    says it is a preview."""
    if len(request.body) > PREVIEW_BYTES:
        return JsonResponse({'error': 'too large'}, status=413)
    try:
        asked = json.loads(request.body)
        unit = Tank.objects.select_related('production_department__site', 'system').get(pk=UUID(str(asked['unit'])))
    except (ValueError, KeyError, TypeError, Tank.DoesNotExist):
        return JsonResponse({'error': 'bad request'}, status=400)
    layout = asked.get('layout')
    # (a fitted template's measure, as the form has it now: the card is then drawn fitted, at that measure)
    measure = asked.get('measure')
    if measure is not None:
        if not (isinstance(measure, list) and len(measure) == 2 and all(type(each) is int for each in measure)
                and catalogue.MEASURE_W[0] <= measure[0] <= catalogue.MEASURE_W[1]
                and catalogue.MEASURE_H[0] <= measure[1] <= catalogue.MEASURE_H[1]):
            return JsonResponse({'error': 'bad request'}, status=400)
        measure = tuple(measure)
    problems = validate.validate(layout, measure)
    found = [problem.as_data() for problem in problems]
    if any(problem.severity == validate.ERROR for problem in problems):
        return JsonResponse({'html': '', 'problems': found})
    name = str(asked.get('name') or '').strip()[:100] or _('New template')
    chosen = resolve.Resolved(SimpleNamespace(pk='', shown_name=name, expanded_id=None, measure=measure),
                              validate.upgrade(layout), resolve.PREVIEW)
    try:
        cards = read.cards([unit], request.user, resolve.Choice(preview=chosen), read.ALL)
    except read.Unavailable:
        return _unavailable()
    if not cards:
        return JsonResponse({'html': '', 'problems': found})
    card = cards[0]
    if asked.get('state') in read.RANK and asked['state'] != read.EMPTY_STATE:
        card.__dict__['state'] = read.State(asked['state'], card.state.reasons, card.state.basis)   # the preview only
    html = render_to_string('monitoring/_card.html', {'row': {'card': card, 'flip': {}, 'preview': True}}, request)
    return JsonResponse({'html': html, 'problems': found})

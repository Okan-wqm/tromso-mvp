"""Operations › Monitoring: the wall. The page (`monitor`) is the toolbar and a grid of cards, one per tank, pond or cage,
simple or detailed; the fragment (`cards`) is the grid's children, which the browser asks for again (frontend/poll.ts)
and which the server answers without a body while nothing has changed. Both are composed by monitoring/read.py from the
other modules' own reads; nothing is stored or written here, a poll included, except that a wall (`?wall=1`) keeps its
session alive once a day.

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

from core import audit, navigation
from core.dates import company_today, company_zone
from core.crud import render_page
from farm.models import ProductionDepartment, Site, System, Tank
from farm.stock.views import VIEW

from . import read
from .cards import resolve, validate
from .models import CardTemplate, CardWidth, MonitorBoard

POLL = 'monitoring:cards'
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


def _poll_url(query, token):
    return f'{reverse(POLL)}?{query}{"&" if query else ""}{urlencode({"after": token})}'


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
    return {
        'rows': [{'card': card, 'flip': _flip_urls(params, card)} for card in found], 'band': read.band(found),
        'modes': _modes(params, board), 'params': params, 'card_width': board.card_width if board is not None else CardWidth.AUTO,
        'computed_at': timezone.make_naive(now, company_zone()),     # naive: a template shows an aware one in UTC
        'shown': len(found), 'on_farm': farm,
        'count_line': ngettext('%(shown)d of %(farm)d unit shown', '%(shown)d of %(farm)d units shown', farm)
        % {'shown': len(found), 'farm': farm},
    }


# How a screen's cards can be drawn, as the toolbar's choice and the band's switch name them. Small is a VIEW: every
# card of the screen, whatever the rules and the board say (monitoring/cards/resolve.py). Without a board, '' is the
# farm's own rules (Simple where it has made none) and Detailed the page's choice below them; on a board, '' is the
# board's own cards.
MODE_CHOICES = ((read.SMALL, gettext_lazy('Small')), ('', gettext_lazy('Simple')), (read.DETAILED, gettext_lazy('Detailed')))
BOARD_CHOICES = ((read.SMALL, gettext_lazy('Small')), ('', gettext_lazy('As the board')))


def _modes(params, board):
    """The band's switch of the screen's cards: [{label, url, current}], each the page drawn with that kind of card and
    no card flipped. Plain links: they work without script, and a wall, which has no toolbar, changes its cards with
    them."""
    page = reverse('monitoring:monitor')
    on_board = board is not None
    chosen = params.mode if params.mode == read.SMALL or (not on_board and params.mode == read.DETAILED) else ''
    found = []
    for key, label in (BOARD_CHOICES if on_board else MODE_CHOICES):
        query = params.canonical(mode=key, flip=frozenset())
        found.append({'label': label, 'url': f'{page}?{query}' if query else page, 'current': key == chosen})
    return found


def _flip_urls(params, card):
    """The Simple/Detailed link of a card: the page with this card flipped (what the address keeps), and the fragment's
    address for that state (data-poll-url: with the script the grid refetches, without it the link navigates)."""
    flip = set(params.flip)
    flip ^= {str(card.unit.pk)}
    changed = params.canonical(flip=frozenset(flip))
    return {'page': f'{reverse("monitoring:monitor")}?{changed}' if changed else reverse('monitoring:monitor'),
            'poll': f'{reverse(POLL)}?{changed}' if changed else reverse(POLL)}


@permission_required(VIEW, raise_exception=True)
def monitor(request):
    """The page: toolbar, grid, the windows' place. The token is read before the cards, so a change between the two
    shows at the first poll."""
    params = read.Params.from_query(request.GET)
    _keep_alive(request, params)
    token = read.change_token(request.user, params.canonical(), board=params.board)
    now = timezone.now()
    board = _board(params)
    try:
        grid = _grid(request, params, board, now)
    except read.Unavailable:
        return _unavailable()
    context = _context(**grid, token=token, query=params.canonical(), board=board,
                       boards=MonitorBoard.objects.order_by('name'),
                       poll_url=_poll_url(params.canonical(), token),
                       poll_seconds=board.seconds if board else settings.MONITOR_POLL_SECONDS,
                       wall=params.wall, windows_key=params.board or 'adhoc',
                       wall_url=f'{reverse("monitoring:monitor")}?{params.canonical(wall=True)}',
                       page_url=reverse('monitoring:monitor') + (f'?{params.canonical(wall=False)}' if params.canonical(wall=False) else ''),
                       sites=Site.objects.order_by('name'), departments=ProductionDepartment.objects.order_by('name'),
                       systems=System.objects.order_by('name'), all_units=Tank.objects.order_by('code'),
                       kinds=[(Tank.Kind.TANK, _('Tanks')), (Tank.Kind.POND, _('Ponds')), (Tank.Kind.CAGE, _('Cages'))],
                       occupancies=[(read.STOCKED, pgettext('occupancy', 'Stocked')), (read.EMPTY, _('Empty')),
                                    (read.ALL, _('All'))])
    return render_page(request, 'monitoring/monitor.html', context)


@permission_required(VIEW, raise_exception=True)
def cards(request):
    """The grid's children for the address: 204 with the same next address while nothing has changed since `after`,
    else 200 with the cards and the next address (X-Poll-Next) carrying the new token. No request goes to the
    template, so the shell's context (the menu, the unread count) is never worked out for a poll."""
    params = read.Params.from_query(request.GET)
    _keep_alive(request, params)
    query = params.canonical()
    token = read.change_token(request.user, query, board=params.board)
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
    """The designer's preview: {layout, unit, name?, state?} as JSON; answers {html, problems}. The layout is checked by
    the validator first (an error draws nothing), then the same card read and the same _card.html as the wall draw it for
    that one unit, with the previewer's own rights. Nothing is written and nothing is logged. `state` forces the frame's
    state for a look at it; it is accepted here only, and the card says it is a preview."""
    if len(request.body) > PREVIEW_BYTES:
        return JsonResponse({'error': 'too large'}, status=413)
    try:
        asked = json.loads(request.body)
        unit = Tank.objects.select_related('production_department__site', 'system').get(pk=UUID(str(asked['unit'])))
    except (ValueError, KeyError, TypeError, Tank.DoesNotExist):
        return JsonResponse({'error': 'bad request'}, status=400)
    layout = asked.get('layout')
    problems = validate.validate(layout)
    found = [problem.as_data() for problem in problems]
    if any(problem.severity == validate.ERROR for problem in problems):
        return JsonResponse({'html': '', 'problems': found})
    name = str(asked.get('name') or '').strip()[:100] or _('New template')
    chosen = resolve.Resolved(SimpleNamespace(pk='', shown_name=name, expanded_id=None), validate.upgrade(layout),
                              resolve.PREVIEW)
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

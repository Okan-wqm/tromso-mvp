"""Operations › Monitoring: the wall. The page (`monitor`) is the toolbar and a grid of cards, one per tank, pond or cage,
simple or detailed; the fragment (`cards`) is the grid's children, which the browser asks for again (frontend/poll.ts)
and which the server answers without a body while nothing has changed. Both are composed by monitoring/read.py from the
other modules' own reads; nothing is stored or written here, a poll included, except that a wall (`?wall=1`) keeps its
session alive once a day.

Who may read it: the right to read stock operations (the page's gate, as Production units); each section of a card needs
its own right (monitoring/read.py `sections_for`) and the card says so for one the person may not read. The fragment has
the same gate. The Deffeyes chart in a card's window is the water page's endpoint (farm:water_unit_chart), which needs
the right to read water samples."""
from urllib.parse import urlencode

from django.conf import settings
from django.contrib.auth.decorators import permission_required
from django.http import HttpResponse
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import gettext as _, ngettext, pgettext

from core import navigation
from core.crud import render_page
from farm.models import ProductionDepartment, Site, System, Tank
from farm.water import parameters
from farm.stock.views import VIEW

from . import read
from .cards import resolve
from .models import MonitorBoard

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
    today = timezone.localdate().isoformat()
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
    """The context of the grid: the cards after the filters and the occupancy, how many units are not shown, and the
    strip of the cards that need a look."""
    units = read.units_for(params, board)
    found = read.cards(units, request.user, resolve.Choice.of(board, params), params.occupancy, now)
    farm = Tank.objects.count()
    return {
        'rows': [{'card': card, 'flip': _flip_urls(params, card)} for card in found], 'strip': read.attention(found),
        'water_labels': [(code, parameters.get(code).short) for code in read.KEY_WATER],
        'params': params, 'computed_at': timezone.localtime(now), 'shown': len(found), 'on_farm': farm,
        'count_line': ngettext('%(shown)d of %(farm)d unit shown', '%(shown)d of %(farm)d units shown', farm)
        % {'shown': len(found), 'farm': farm},
    }


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

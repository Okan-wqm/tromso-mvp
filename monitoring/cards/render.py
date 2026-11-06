"""How a card's widgets are drawn: `build(card)` turns the card's template into the widgets to render, pure (no query:
every figure is already on the card), in reading order (y, then x), so the order a screen reader reads, the order Tab
moves in and the order the eye follows agree. The server places them with plain CSS grid (templates/monitoring/_card.html,
static/css/monitor.css); the wall runs no layout script.

`face(reading, now)` is THE one way a single water value is said on a card (the value and bar widgets): the figure at
the parameter's precision, its status, where it came from and how old it is, in words, and "no data" rather than a dash.
The age is said in bands (`age_text`), so the card's bytes change once per band, not at every poll."""
from dataclasses import dataclass

from django.utils.translation import gettext

from core import text
from farm.templatetags.water import water_value
from farm.water import read as water_read
from farm.water.evaluate import Status, judge

from . import catalogue

# Which section a widget's sources fall under when the person may not read them, for its "not shown to you" line:
# the first of its sources the person cannot read decides (a health widget needs one of its three).
HIDDEN_AS = {'feeding': 'feeding', 'water': 'water', 'events': 'health', 'treatments': 'health', 'lice': 'health',
             'tasks': 'tasks'}


@dataclass(frozen=True)
class WidgetView:
    id: str
    type: str
    x: int
    y: int
    w: int
    h: int
    renderer: str
    opts: dict
    bind: dict
    hidden: str          # '' or the section the person may not read ('feeding', 'water', 'health', 'tasks')
    failed: bool         # a source of it could not be read: it says "no data"
    dom_id: str          # w-<unit>-<widget id>: what a focusable element in it is called (poll.ts restores focus by id)

    @property
    def style(self):
        return f'--x:{self.x};--y:{self.y};--w:{self.w};--h:{self.h}'

    @property
    def large(self):
        return self.opts.get('size') == 'large'


def _hidden(spec, sections):
    readable = [source for source in spec.sources if source not in HIDDEN_AS or source in sections]
    if readable:
        return ''
    return HIDDEN_AS[spec.sources[0]]


def build(card):
    """The card's widgets to draw, in reading order; on the card of a unit with no fish, only the ones that belong
    there (the experiments' chips, the Deffeyes chart button)."""
    views = []
    widgets = sorted(card.template.layout['widgets'], key=lambda widget: (widget['y'], widget['x']))
    for widget in widgets:
        spec = catalogue.WIDGETS[widget['type']]
        if card.stock is None and not spec.on_empty:
            continue
        hidden = _hidden(spec, card.sections)
        if hidden and not spec.says_hidden:
            continue
        views.append(WidgetView(
            widget['id'], spec.type, widget['x'], widget['y'], widget['w'], widget['h'], spec.renderer,
            widget.get('opts', {}), widget.get('bind', {}), hidden,
            any(source in card.failed for source in spec.sources), f'w-{card.unit.pk}-{widget["id"]}'))
    return tuple(views)


# ---- one value -------------------------------------------------------------------------------------------------
@dataclass(frozen=True)
class Face:
    label: str           # the parameter's short label, with its unit
    value: str           # the figure at the parameter's precision, or "no data"
    status: str          # the water's own status (evaluate.Status), '' when there is no value
    status_label: str
    origin: str          # where it came from (the sample's source), '' when unknown
    age: str             # how old, in a band ("1 h ago"), '' when there is no reading
    stale: bool          # older than the parameter's freshness
    missing: bool
    reading: object = None


def age_text(seconds):
    seconds = max(int(seconds), 0)
    if seconds < 10:
        return gettext('just now')
    if seconds < 60:
        return gettext('%(seconds)d s ago') % {'seconds': seconds // 10 * 10}
    if seconds < 3600:
        return gettext('%(minutes)d min ago') % {'minutes': seconds // 60}
    if seconds < 86400:
        return gettext('%(hours)d h ago') % {'hours': seconds // 3600}
    return gettext('%(days)d d ago') % {'days': seconds // 86400}


def face(reading, now, parameter=None):
    """A water value as a card says it. `parameter` names it when there is no reading at all."""
    parameter = reading.parameter if reading is not None else parameter
    label = str(parameter.short) if parameter is not None else ''
    if reading is None:
        return Face(label, gettext('no data'), '', '', '', '', False, True)
    # A sample says how it was taken (its source); a live value which sensor gave it (owner rule A1, farm/water/read.py).
    sample = getattr(reading.sample, 'sample', None)
    origin = str(sample.get_source_display()) if sample is not None else water_read.origin_text(reading)
    age = age_text((now - reading.at).total_seconds())
    missing = reading.value is None
    status = '' if missing else str(reading.status)
    return Face(label, gettext('no data') if missing else water_value(reading.value, reading.code), status,
                str(Status(reading.status).label) if status else '', origin, age,
                not reading.fresh(now), missing, reading)


def reading_at(card, code, point_kind):
    """The reading of `code` at the card's point of that kind (the middle by default), or None."""
    for water in card.water:
        if water.point is not None and water.point.kind == point_kind:
            return water.get(code)
    return None


# ---- a value against its limits --------------------------------------------------------------------------------
@dataclass(frozen=True)
class Band:
    kind: str            # 'critical', 'warning' or 'ok': drawn by dash pattern as well as tone (never colour alone)
    start: float         # per cent of the bar
    width: float


@dataclass(frozen=True)
class Bar:
    bands: tuple
    marker: float        # per cent of the bar where the value is
    sentence: str        # what the picture shows, said (the image's accessible name)


BOUNDS = ('critical_low', 'warning_low', 'warning_high', 'critical_high')


def bar(face):
    """The bar of a value against the water limit that judged it, or None when there is no value or no limit (the
    widget then says so). The limit's four bounds cut the scale into bands; the scale reaches a tenth beyond them."""
    reading = face.reading
    if reading is None or reading.value is None or not reading.limits:
        return None
    limit = reading.limits[0]
    bounds = {name: getattr(limit, name) for name in BOUNDS}
    known = [value for value in bounds.values() if value is not None]
    if not known:
        return None
    low, high = min([*known, reading.value]), max([*known, reading.value])
    pad = (high - low) / 10 or 1
    low, high = low - pad, high + pad
    span = high - low

    def at(value):
        return round(float((value - low) / span * 100), 2)

    # Each stretch between two bounds is what the one rule (evaluate.judge) says of a value inside it, so an open bound
    # draws no band of its own: limits with upper bounds only are ok below them, never critical.
    edges = [low, *sorted(set(known)), high]
    bands = []
    for start, end in zip(edges, edges[1:]):
        if end <= start:
            continue
        kind = str(judge((start + end) / 2, limit))
        if bands and bands[-1].kind == kind:
            last = bands.pop()
            bands.append(Band(kind, last.start, round(at(end) - last.start, 2)))
        else:
            bands.append(Band(kind, at(start), round(at(end) - at(start), 2)))
    shown = ', '.join(f'{label} {water_value(bounds[name], reading.code)}'
                      for name, label in zip(BOUNDS, (gettext('critical below'), gettext('warning below'),
                                                      gettext('warning above'), gettext('critical above')))
                      if bounds[name] is not None)
    sentence = gettext('%(label)s %(value)s, %(status)s; limits: %(limits)s') % {
        'label': face.label, 'value': face.value, 'status': text.lower(face.status_label), 'limits': shown}
    return Bar(tuple(bands), at(reading.value), sentence)

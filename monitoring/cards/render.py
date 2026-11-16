"""How a card's widgets are drawn: `build(card)` turns the card's template into the widgets to render, pure (no query:
every figure is already on the card), in reading order (y, then x), so the order a screen reader reads, the order Tab
moves in and the order the eye follows agree. The server places them with plain CSS grid (templates/monitoring/_card.html,
static/css/monitor.css); the wall runs no layout script. A widget's cell is said by classes (`WidgetView.place`), never a
style attribute, which the Content-Security-Policy blocks: static/css/card-grid.css (`grid_css`) turns each into the
grid's --x, --y, --w, --h.

`face(reading, now)` is THE one way a single water value is said on a card (the value and bar widgets): the figure at
the parameter's precision, its status, where it came from and how old it is, in words, and "no data" rather than a dash.
The age is said in bands (`age_text`), so the card's bytes change once per band, not at every poll."""
from dataclasses import dataclass

from django.utils.translation import gettext

from core import text
from farm.templatetags.stock import number, percent
from farm.templatetags.water import water_value
from farm.water import calculation, deffeyes, parameters, read as water_read
from farm.water.evaluate import ALERTS, Status, judge

from . import catalogue

# Which section a widget's sources fall under when the person may not read them, for its "not shown to you" line:
# the first of its sources the person cannot read decides (a health widget needs one of its three).
HIDDEN_AS = {'feeding': 'feeding', 'water': 'water', 'events': 'health', 'treatments': 'health', 'lice': 'health',
             'tasks': 'tasks', 'chart': 'water'}
# A source worked out from another's answer is read with that one's right (monitoring/read.py Source.of): the unit's
# chart with the water's.
READ_WITH = {'chart': 'water'}


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
    def place(self):
        """The classes of its cell and size: 'gx-0 gy-3 gw-6 gh-2' (static/css/card-grid.css)."""
        return f'gx-{self.x} gy-{self.y} gw-{self.w} gh-{self.h}'

    @property
    def large(self):
        return self.opts.get('size') == 'large'


def _hidden(spec, sections):
    readable = [source for source in spec.sources
                if source not in HIDDEN_AS or READ_WITH.get(source, source) in sections]
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
    note: str = ''           # what a worked-out value was worked out from, or why it could not be
    source: str = ''         # where it came from in ONE word: sensor, sample, calc. (the line under a fitted figure)
    age_short: str = ''      # how old, without "ago": 12 s, 5 min, 3 h, 7 d ('' when there is no reading)


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


def age_short(seconds):
    """An age in the fewest letters, in the bands of `age_text`: under a figure on a wall there is room for no more,
    and the line it stands in is about nothing else ("sensor · 12 s")."""
    seconds = max(int(seconds), 0)
    if seconds < 10:
        return gettext('now')
    if seconds < 60:
        return gettext('%(seconds)d s') % {'seconds': seconds // 10 * 10}
    if seconds < 3600:
        return gettext('%(minutes)d min') % {'minutes': seconds // 60}
    if seconds < 86400:
        return gettext('%(hours)d h') % {'hours': seconds // 3600}
    return gettext('%(days)d d') % {'days': seconds // 86400}


def face(reading, now, parameter=None):
    """A water value as a card says it. `parameter` names it when there is no reading at all."""
    parameter = reading.parameter if reading is not None else parameter
    label = str(parameter.short) if parameter is not None else ''
    if reading is None:
        return Face(label, gettext('no data'), '', '', '', '', False, True)
    # A sample says how it was taken (its source); a live value which sensor gave it (owner rule A1, farm/water/read.py).
    sample = getattr(reading.sample, 'sample', None)
    origin = str(sample.get_source_display()) if sample is not None else water_read.origin_text(reading)
    seconds = (now - reading.at).total_seconds()
    age = age_text(seconds)
    missing = reading.value is None
    status = '' if missing else str(reading.old_alert or reading.status)
    return Face(label, gettext('no data') if missing else water_value(reading.value, reading.code), status,
                str(Status(status).label) if status else '', origin, age,
                not reading.fresh(now), missing, reading, str(reading.note or ''),
                gettext('sample') if sample is not None else gettext('sensor'), age_short(seconds))


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


# ---- a value the unit's chart works out, and the pH window -----------------------------------------------------------
def _refused(chart):
    """Why a unit's chart could not be worked out (calculation.Refusal), in a few words."""
    if chart.no_point:
        return gettext('no active middle sampling point')
    if chart.missing:
        return gettext('no value of %(values)s') % {'values': ', '.join(str(label) for label in chart.missing)}
    return str(chart.impossible)


def calculated(card, value):
    """The Face of a value the unit's chart works out (`value`: a catalogue.Calculated), from the card's chart: the
    figure at its precision, tagged "calculated", as old as the oldest of the four values it is worked out from and
    `stale` when one of them is old (owner decision 1: shown, and said). Phase 1: it has no status, the limits do not
    judge it yet. "no data" when the chart could not be worked out, the note saying why."""
    label = str(value.short)
    chart = card.chart
    if not isinstance(chart, calculation.UnitChart):
        why = '' if chart is None else gettext('Not worked out: %(why)s.') % {'why': _refused(chart)}
        return Face(label, gettext('no data'), '', '', '', '', False, True, note=why)
    figure = water_read.as_parameter(value.shown_as, getattr(chart.calculation.analysis, value.figure))
    made_from = [item for item in chart.inputs if item.field in calculation.REQUIRED]
    measured = [item.reading.at for item in made_from if item.reading is not None]
    note = gettext('Calculated from the pH, the alkalinity, the temperature and the salinity.')
    if chart.assumed:
        note = '{} {}'.format(note, gettext('The salinity is assumed: fresh water.'))
    seconds = (card.now - min(measured)).total_seconds() if measured else None
    return Face(label, water_value(figure, value.shown_as), '', '', gettext('calculated'),
                age_text(seconds) if measured else '', any(item.old for item in made_from), False, note=note,
                source=gettext('calc.'), age_short=age_short(seconds) if measured else '')


def bound(card, view):
    """The Face of what a value or bar widget is bound to: a water parameter at its point (the middle by default), or a
    value the unit's chart works out."""
    code = view.bind.get('parameter')
    if code in catalogue.CALCULATED:
        return calculated(card, catalogue.CALCULATED[code])
    return face(reading_at(card, code, view.bind.get('point', water_read.MIDDLE)), card.now, parameters.get(code))


@dataclass(frozen=True)
class Tile:
    """A value on a FITTED card: one short label, the figure, one line under it (monitoring/widgets/_value_fit.html)."""
    label: str           # 'O₂', '°C', 'CO₂ calc.': catalogue.TILE_LABELS, else the parameter's short label
    title: str           # the full label
    face: Face
    alert: str           # 'critical' or 'warning' when the limits say so of the value (an old one too), else ''
    beside: str          # the same quantity in its other unit, said in the label: '98.0 %' beside the oxygen's mg/L
    beside_alert: str


def tile(card, view):
    code = view.bind.get('parameter')
    point = view.bind.get('point', water_read.MIDDLE)
    said = bound(card, view)
    named = catalogue.described(code)
    label, title = str(catalogue.TILE_LABELS.get(code, named.short)), str(named.label)
    if point != water_read.MIDDLE:
        where = said.reading.point.name if said.reading is not None and said.reading.point is not None else point
        label, title = f'{label} · {where}', f'{title} · {where}'
    other = parameters.SAME_QUANTITY.get(code)
    twin = reading_at(card, other, point) if other else None
    beside = beside_alert = ''
    if twin is not None and twin.value is not None:
        beside = percent(twin.value, 1) if other == parameters.OXYGEN_PCT else f'{water_value(twin.value, other)} mg/L'
        status = twin.old_alert or twin.status
        beside_alert = str(status) if status in ALERTS else ''
    return Tile(label, title, said, said.status if said.status in ALERTS else '', beside, beside_alert)


@dataclass(frozen=True)
class PhWindow:
    """The pH window of a card: the chart's one-line slice at the unit's own alkalinity, on the scale of
    catalogue.PH_WINDOW. Left of one border the CO₂ is past its limit, right of the other the NH₃ is; the water's pH is
    the mark. Every length is a percentage of the picture, written with a dot whatever the language. `refused`: why
    there is no picture."""
    label: str = ''          # the picture's name: every number of it in words
    regions: tuple = ()      # (key, x, width): 'co2', 'safe', 'nh3'
    names: tuple = ()        # (key, text, x, inside): a border's number, or what is missing on that side
    water: str = ''
    zones: tuple = ()        # the regions the water is in: 'co2', 'nh3'
    old: bool = False
    refused: str = ''


def _pc(value):
    return f'{value:.1f}'


def ph_window(card):
    """The PhWindow of a card, from its chart (the chemistry core's analysis: the two borders as pH, and whether the
    water is past each). Nothing is judged here: a region is where the core's border says it is, the water is "in" a
    region when the core says it is past that border, and the stretch between the borders is called safe only when the
    core has a safe zone at all (deffeyes.safe_zone_gaps: every limit it needs is set) and the limits judge the unit's
    alkalinity inside its band. A missing limit is never drawn as a safe side: the picture says what is missing."""
    chart = card.chart
    if chart is None:
        return PhWindow(refused=gettext('no data'))
    if not isinstance(chart, calculation.UnitChart):
        return PhWindow(refused=gettext('The pH window cannot be drawn: %(why)s.') % {'why': _refused(chart)})
    analysis = chart.calculation.analysis
    low, high = catalogue.PH_WINDOW

    def at(ph):
        return (min(max(ph, low), high) - low) / (high - low) * 100

    def under(start, end):
        return start - 2 < water < end + 2

    # (a border's number never lies under the water's mark: it goes to the other side of its border, and when the mark
    # is on the border itself, past the mark)

    co2, nh3, water = analysis.co2, analysis.nh3, at(analysis.water.ph)
    left = 100.0 if co2.everywhere else at(co2.ph) if co2.ph is not None else 0.0
    right = 0.0 if nh3.everywhere else at(nh3.ph) if nh3.ph is not None else 100.0
    alkalinity = next((item.reading for item in chart.inputs if item.field == 'alkalinity_mg_l'), None)
    safe = (not deffeyes.safe_zone_gaps(analysis) and alkalinity is not None and alkalinity.judged == Status.OK)
    regions = []
    if left > 0:
        regions.append(('co2', _pc(0), _pc(left)))
    if safe and right > left:
        regions.append(('safe', _pc(left), _pc(right - left)))
    if right < 100:
        regions.append(('nh3', _pc(right), _pc(100 - right)))
    said = [gettext('pH %(ph)s') % {'ph': number(analysis.water.ph, 2)}]
    names = []
    if co2.everywhere:
        names.append(('co2', 'CO₂', _pc(1.2), True))
        said.append(gettext('CO₂ is past its limit at every pH'))
    elif co2.ph is not None:
        if left > 0:
            outside = left >= 17 and not under(left - 15, left)
            names.append(('co2', f'CO₂ {number(co2.ph, 2)}',
                          _pc(left - 1.2 if outside else max(left + 1.2, water + 2.6 if under(left, left) else 0)),
                          not outside))
        said.append(gettext('CO₂ passes its limit below pH %(ph)s') % {'ph': number(co2.ph, 2)})
    elif 'co2_limit_mg_l' not in chart.limits:
        names.append(('co2', gettext('no CO₂ limit'), _pc(1.2), True))
        said.append(gettext('no CO₂ limit for these fish'))
    else:
        said.append(gettext('CO₂ does not reach its limit'))
    if nh3.everywhere:
        names.append(('nh3', 'NH₃', _pc(98.8), True))
        said.append(gettext('NH₃ is past its limit at every pH'))
    elif nh3.ph is not None:
        if right < 100:
            outside = right <= 83 and not under(right, right + 15)
            names.append(('nh3', f'{number(nh3.ph, 2)} NH₃',
                          _pc(right + 1.2 if outside else min(right - 1.2, water - 2.6 if under(right, right) else 100)),
                          not outside))
        said.append(gettext('NH₃ passes its limit above pH %(ph)s') % {'ph': number(nh3.ph, 2)})
    elif 'nh3_n_limit_mg_l' not in chart.limits:
        names.append(('nh3', gettext('no NH₃ limit'), _pc(98.8), True))
        said.append(gettext('no NH₃ limit for these fish'))
    elif nh3.status == Status.NOT_MEASURED:
        names.append(('nh3', gettext('no TAN'), _pc(98.8), True))
        said.append(gettext('NH₃ not assessed: no TAN'))
    else:
        said.append(gettext('NH₃ does not reach its limit'))
    if chart.old:
        said.append(gettext('last known position, old: %(values)s') % {
            'values': ', '.join(str(parameters.get(item.field).short) for item in chart.old)})
    label = gettext('pH window, %(unit)s: %(said)s') % {'unit': card.unit.code, 'said': '; '.join(said)}
    zones = tuple(key for key, border in (('co2', co2), ('nh3', nh3)) if border.status == Status.CRITICAL)
    return PhWindow(label, tuple(regions), tuple(names), _pc(water), zones, bool(chart.old))


def grid_css():
    """static/css/card-grid.css: a class for every column, row, width and height a valid layout can use (catalogue),
    each setting the custom property monitor.css places a widget by. Written by `manage.py card_grid_css`."""
    tallest = max(spec.max_h for spec in catalogue.WIDGETS.values())
    lines = ['/* Made by `manage.py card_grid_css` from monitoring/cards/catalogue.py: do not edit. A widget\'s cell on its',
             '   card is said by classes (monitoring.cards.render.WidgetView.place), since the Content-Security-Policy',
             '   allows no style attribute; monitor.css places .card-grid > .w by --x, --y, --w and --h. */']
    lines += [f'.gx-{x}{{--x:{x}}}' for x in range(catalogue.COLUMNS)]
    lines += [f'.gw-{w}{{--w:{w}}}' for w in range(1, catalogue.COLUMNS + 1)]
    lines += [f'.gh-{h}{{--h:{h}}}' for h in range(1, tallest + 1)]
    lines += [f'.gy-{y}{{--y:{y}}}' for y in range(catalogue.ROWS)]
    # A fitted card (a template with a measure): the rows its widgets share its height in, and its measure in card units.
    lines += [f'.gr-{rows}{{--gr:{rows}}}' for rows in range(1, catalogue.FIT_ROWS + 1)]
    lines += [f'.mw-{width}{{--mw:{width}}}' for width in range(catalogue.MEASURE_W[0], catalogue.MEASURE_W[1] + 1)]
    lines += [f'.mh-{height}{{--mh:{height}}}' for height in range(catalogue.MEASURE_H[0], catalogue.MEASURE_H[1] + 1)]
    return '\n'.join(lines) + '\n'

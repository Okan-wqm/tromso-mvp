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

from django.utils import timezone
from django.utils.formats import date_format
from django.utils.translation import gettext

from core import text
from core.dates import company_zone
from farm.templatetags.stock import number, percent
from farm.templatetags.water import proof_of, reading_figure, water_value
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
    titled: bool = False  # it says its name over what it shows (a box of the Big card), where its place has the room

    @property
    def place(self):
        """The classes of its cell and size: 'gx-0 gy-3 gw-6 gh-2' (static/css/card-grid.css)."""
        return f'gx-{self.x} gy-{self.y} gw-{self.w} gh-{self.h}'

    @property
    def large(self):
        return self.opts.get('size') == 'large'

    @property
    def next_renderer(self):
        """Its markup on a card that flows in the new look (templates/monitoring/_card_next.html): its own where the
        design draws it otherwise (NEXT_LOOK), else the classic one, which the new look's sheet restyles."""
        return f'monitoring/widgets/next/_{self.type}.html' if self.type in NEXT_LOOK else self.renderer

    @property
    def in_foot(self):
        """Whether the new look draws it in the card's foot, among the card's actions, rather than in its grid: the
        Deffeyes chart's button, which opens the unit's chart in the movable window, as the design's button does."""
        return self.type in FOOT


# The widgets a card that flows draws with markup of its own in the new look (templates/monitoring/widgets/next/): the
# feeding as the design's "Next meal" box. Every other widget keeps its classic markup there, restyled by
# static/css/monitor-next.css. The ones it draws in the card's foot, as actions: the Deffeyes chart's button.
NEXT_LOOK = frozenset({'feeding'})
FOOT = frozenset({'deffeyes'})


def _hidden(spec, sections):
    readable = [source for source in spec.sources
                if source not in HIDDEN_AS or READ_WITH.get(source, source) in sections]
    if readable:
        return ''
    return HIDDEN_AS[spec.sources[0]]


# The boxes of a fitted card that say their name over what they show (the design's three boxes under the Big card's
# values: Dosing advice, Other sampling points, Stock), when their place is this many card units higher than what they
# print needs (catalogue fit_units): the name is one line of the smallest step, never squeezed into a place too low.
TITLED = frozenset({'dosing', 'points', 'stock'})
TITLE_UNITS = 1.2


def _titled(spec, widget, rows, measure):
    if spec.type not in TITLED or not measure or not spec.fit_units:
        return False
    from .validate import fitted_place
    return fitted_place(widget, rows, measure)[1] >= spec.fit_units[1] + TITLE_UNITS


def build(card):
    """The card's widgets to draw, in reading order; on the card of a unit with no fish, only the ones that belong
    there (the experiments' chips, the Deffeyes chart button)."""
    return _views(card, lambda spec: card.stock is not None or spec.on_empty)


def _views(card, drawn):
    """The WidgetViews of the card's template whose spec `drawn` keeps, in reading order (y, then x)."""
    views = []
    widgets = sorted(card.template.layout['widgets'], key=lambda widget: (widget['y'], widget['x']))
    rows = max((widget['y'] + widget['h'] for widget in widgets), default=0)
    measure = getattr(card.template, 'measure', None)
    for widget in widgets:
        spec = catalogue.WIDGETS[widget['type']]
        if not drawn(spec):
            continue
        hidden = _hidden(spec, card.sections)
        if hidden and not spec.says_hidden:
            continue
        views.append(WidgetView(
            widget['id'], spec.type, widget['x'], widget['y'], widget['w'], widget['h'], spec.renderer,
            widget.get('opts', {}), widget.get('bind', {}), hidden,
            any(source in card.failed for source in spec.sources), f'w-{card.unit.pk}-{widget["id"]}',
            _titled(spec, widget, rows, measure)))
    return tuple(views)


def shown(card, next_look):
    """The widgets a fitted card draws: its template's (`build`), and in the new look, on a full-height card of a unit
    with no fish, the widgets the catalogue draws there too (WidgetSpec.on_empty_next: the design's Big card of an empty
    unit, the chart's place saying there is no fish, what to dose, the other points and the stock), in reading order.
    The classic look's are `build`'s, unchanged."""
    if not next_look or card.stock is not None or not card.template.fill:
        return card.widgets
    return _views(card, lambda spec: spec.on_empty or spec.on_empty_next)


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
    note: str = ''           # what a worked-out value was worked out from and by (its formula), or why it could not be
    source: str = ''         # where it came from in ONE word: sensor, sample, calc. (the line under a fitted figure)
    age_short: str = ''      # how old, without "ago": 12 s, 5 min, 3 h, 7 d ('' when there is no reading)
    # What was measured where the value is stored converted (a pH on another scale than NBS, a phosphate entered as PO₄)
    # or is the safe-side basis alone: read.Reading.measured, the few words every page prints visibly beside the number.
    measured: str = ''


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
    # A value the fish have a limit for that the chemistry core refused to work out (Reading.unevaluated) keeps its
    # status even without a figure: it is "cannot be evaluated" in words, never "no data" (the water page's rule).
    status = '' if missing and not reading.unevaluated else str(reading.old_alert or reading.status)
    value = reading_figure(reading) if not missing else (
        str(Status.UNEVALUATED.label) if reading.unevaluated else gettext('no data'))
    return Face(label, value, status,
                str(Status(status).label) if status else '', origin, age,
                not reading.fresh(now), missing, reading,
                ' '.join(str(said) for said in (reading.note, reading.provenance) if said),
                gettext('sample') if sample is not None else gettext('sensor'), age_short(seconds),
                str(reading.measured or ''))


def reading_at(card, code, point_kind):
    """The reading of `code` at the card's point of that kind (the middle by default), or None."""
    for water in card.water:
        if water.point is not None and water.point.kind == point_kind:
            return water.get(code)
        if water.point is None and water.for_unit and point_kind == water_read.MIDDLE:
            return water.get(code)          # a unit without a point: its water read at its system stands for it
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
    # What it was worked out by (the formula and the ionic strength), as every page that shows a worked-out value says
    # it (Analysis.provenance). The figure is the core's judged CO₂ (formula 4's safe side); its best estimate and the
    # sentence of which value judged it (Analysis.co2_judged, some 400 letters) stay on the unit's chart page and the
    # calculator: a small card's weight is bounded (test_small) and the calculated CO₂ is not judged on a card yet.
    note = ' '.join(str(said) for said in (note, chart.calculation.analysis.provenance) if said)
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
        beside = (percent(*(proof_of(twin) or (twin.value, 1))) if other == parameters.OXYGEN_PCT
                  else f'{reading_figure(twin)} mg/L')
        beside_alert = str(twin.old_alert or twin.status)
    return Tile(label, title, said, alert_of(said.status), beside, alert_of(beside_alert))


def alert_of(status):
    """The state's shape and tone a value is drawn in: 'critical' or 'warning' as the limits judged it, 'warning' for a
    value the chemistry core refused to work out where the fish have a limit ("cannot be evaluated": never OK, below a
    judged warning, as the water page's chip and the unit's state take it), else ''."""
    if status == Status.UNEVALUATED:
        return str(Status.WARNING)
    return str(status) if status in ALERTS else ''


@dataclass(frozen=True)
class PhWindow:
    """The pH window of a card: the chart's one-line slice at the unit's own alkalinity, on the scale the farm has
    set for the unit's water type (card.ph_scale: monitoring.PhWindowScale, owner decision 15). Left of one border the CO₂ is past its limit, right of the other the NH₃ is; the water's pH is
    the mark. Every length is a percentage of the picture, written with a dot whatever the language. `refused`: why
    there is no picture."""
    label: str = ''          # the picture's name: every number of it in words
    regions: tuple = ()      # (key, x, width): 'co2', 'safe', 'nh3'
    names: tuple = ()        # (key, text, x, anchor): a border's number, or what is missing ('co2', 'nh3', 'band');
                             # placed by `place_names`, never over each other or the water's mark
    water: str = ''
    zones: tuple = ()        # the regions the water is in: 'co2', 'nh3'
    old: bool = False
    refused: str = ''
    off: str = ''            # 'low' or 'high': the water's pH lies beyond that end of the scale (owner decision 15)
    off_text: str = ''       # then, instead of the mark: an arrow and the number


def _pc(value):
    return f'{value:.1f}'


# ---- where the pH window's words stand ---------------------------------------------------------------------------
# Lengths are per cent of the picture. A word's width is not known to the server (the browser sets the type), so it is
# reckoned from its letters: a letter of the window's small text (0.8 of the card's unit) is at most NAME_EM of it wide
# in the product's face, and the picture is as wide as the widget's columns of the card. The browser layout test holds
# the reckoning to the real boxes (frontend/test/wall.browser.test.ts: no two marks of a window touch).
NAME_EM = 0.6
NAME_SIZE = 0.8
NAME_GAP = 1.2          # between a border and its word, and the least between two words
MARK_HALF = 2.4         # half of the water's mark, with its halo
NAME_EDGE = 0.6         # a word never starts or ends nearer the picture's edge
FLOW_UNITS = 26.0       # the width, in units of its text, of a card that flows (no measure): its least on a desk


def letter_pc(card, view=None):
    """How wide one letter of the pH window's words is, in per cent of the picture, on this card: from the template's
    measure (a fitted card is `measure_w` units wide) and the columns the widget takes."""
    measure = card.template.measure
    units = (measure[0] if measure else FLOW_UNITS) * (view.w if view is not None else catalogue.COLUMNS) / catalogue.COLUMNS
    return 100 * NAME_SIZE * NAME_EM / max(units, 1)


def place_names(left, right, water, co2, nh3, band, letter, off=''):
    """((key, text, x, anchor), ...): where the pH window's words stand, by rule and never over one another, over the
    water's mark or outside the picture. `left`, `right`: the two borders (per cent); `water`: the mark's place, None
    when the pH is off the scale (`off`: the arrow's text at that end is then in the way); `co2`, `nh3`: (text,
    at_border) or None: a border's number, which stands AT its border, or with at_border False what is missing or
    everywhere on that side, which stands at that end of the picture; `band`: the texts (long first) saying that no
    alkalinity band is set, for the stretch between the borders, or (); `letter`: a letter's width (letter_pc).

    The ways a border's word can stand, best first:
      0. in its own region, against its border;
      1. between the borders, against its border, when the stretch between them holds it;
      2. in its own region, moved away from its border past whatever stands in the way (the mark, the other word);
      3. between the borders against its border although it runs on past the other border.
    A word with no border (at_border False) stands at its end of the picture (0), or moved inwards past what stands in
    the way (2). Of every pair of ways in which nothing touches, the pair whose worse way is best is taken (then the
    better other way, then CO₂'s). When no pair fits, the word of the border nearer the water stands alone, and the
    other's number is in the picture's name only (ph_window says every number there). The CO₂ word is always left of
    the NH₃ word. The band's words stand in the middle of the widest free run between the borders when one holds
    them, the short form when only it fits."""
    def wide(text_):
        return len(text_) * letter

    blocked = []
    if water is not None:
        blocked.append((water - MARK_HALF, water + MARK_HALF))
    elif off:
        blocked.append((0.0, NAME_EDGE + wide(off)) if off[0] == '◀' else (100 - NAME_EDGE - wide(off), 100.0))

    def apart(span, other):
        return span[1] + NAME_GAP <= other[0] + 1e-9 or other[1] + NAME_GAP <= span[0] + 1e-9

    def free(span, others):
        return (span[0] >= NAME_EDGE - 1e-9 and span[1] <= 100 - NAME_EDGE + 1e-9
                and all(apart(span, other) for other in others))

    def moved(start, width, others, step):
        """The span of `width` nearest `start` in the direction `step` (-1 leftwards: `start` is then its END) that
        nothing of `others` touches, or None when the picture ends first."""
        for _ in range(len(others) + 2):
            span = (start - width, start) if step < 0 else (start, start + width)
            hit = [other for other in others if not apart(span, other)]
            if not hit:
                return span if free(span, ()) else None
            start = min(other[0] for other in hit) - NAME_GAP if step < 0 else max(other[1] for other in hit) + NAME_GAP
        return None

    def stand(key, word, way, others):
        """(x, anchor, span) of a side's word standing in `way` (0 to 3) beside `others`, or None."""
        said, at_border = word
        width = wide(said)
        leftwards = key == 'co2'                     # the CO₂ region lies left of its border, the NH₃ region right
        border = left if leftwards else right
        if not at_border:                            # at its end of the picture, running inwards
            start = NAME_GAP if leftwards else 100 - NAME_GAP
            if way == 0:
                span = (start, start + width) if leftwards else (start - width, start)
            elif way == 2:
                span = moved(start, width, others, 1 if leftwards else -1)
            else:
                span = None
            anchor = 'start' if leftwards else 'end'
        elif way in (0, 2):                          # in its own region
            start = border - NAME_GAP if leftwards else border + NAME_GAP
            if way == 0:
                span = (start - width, start) if leftwards else (start, start + width)
            else:
                span = moved(start, width, others, -1 if leftwards else 1)
            anchor = 'end' if leftwards else 'start'
        else:                                        # between the borders
            start = border + NAME_GAP if leftwards else border - NAME_GAP
            span = (start, start + width) if leftwards else (start - width, start)
            if way == 1 and not (span[1] <= right and span[0] >= left):
                span = None
            anchor = 'start' if leftwards else 'end'
        if span is None or not free(span, others):
            return None
        return (span[0] if anchor == 'start' else span[1]), anchor, span

    def chosen():
        if co2 is None or nh3 is None:
            key, word = ('co2', co2) if nh3 is None else ('nh3', nh3)
            found = None if word is None else next(
                (place for place in (stand(key, word, way, blocked) for way in range(4)) if place), None)
            return (found, None) if key == 'co2' else (None, found)
        pairs = sorted(((a, b) for a in range(4) for b in range(4)), key=lambda pair: (max(pair), sum(pair), pair[0]))
        for way_a, way_b in pairs:
            # (a word that moves, moves past the other one: so each is tried standing first)
            for co2_first in (True, False):
                if co2_first:
                    a = stand('co2', co2, way_a, blocked)
                    b = a and stand('nh3', nh3, way_b, [*blocked, a[2]])
                else:
                    b = stand('nh3', nh3, way_b, blocked)
                    a = b and stand('co2', co2, way_a, [*blocked, b[2]])
                if a and b and a[2][1] <= b[2][0]:
                    return a, b
        # no pair fits: the word of the border nearer the water alone (CO₂'s when neither is, or there is no mark)
        near_nh3 = water is not None and abs(water - right) < abs(water - left)
        for key, word in ((('nh3', nh3), ('co2', co2)) if near_nh3 else (('co2', co2), ('nh3', nh3))):
            for way in range(4):
                found = stand(key, word, way, blocked)
                if found:
                    return (found, None) if key == 'co2' else (None, found)
        return None, None

    a, b = chosen()
    names, taken = [], list(blocked)
    for key, word, place in (('co2', co2, a), ('nh3', nh3, b)):
        if place is not None:
            names.append((key, word[0], _pc(place[0]), place[1]))
            taken.append(place[2])
    if band and right > left:
        # the free runs between the borders, widest first
        edges = sorted((max(start, left), min(end, right)) for start, end in taken if end > left and start < right)
        runs, at = [], left
        for start, end in edges:
            runs.append((at, start))
            at = max(at, end)
        runs.append((at, right))
        start, end = max(runs, key=lambda run: run[1] - run[0])
        for text_ in band:
            if end - start >= wide(text_) + 2 * NAME_GAP:
                names.append(('band', text_, _pc((start + end) / 2), 'middle'))
                break
    return tuple(names)


def ph_window(card, view=None):
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
    if not card.ph_scale:
        # (never a scale of the code's own: the farm's row for this water is gone or could not be read)
        return PhWindow(refused=gettext('The pH window cannot be drawn: no scale is set for %(water)s.') % {
            'water': text.lower(str(card.unit.get_water_type_display()))})
    analysis = chart.calculation.analysis
    low, high = card.ph_scale

    def at(ph):
        return (min(max(ph, low), high) - low) / (high - low) * 100


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
    # (owner decision 15, 2026-11-16) a pH beyond the scale is never drawn on its end as if it were there: an arrow
    # and the number stand at that end, and the picture's words say it is off the scale
    off = 'low' if analysis.water.ph < low else 'high' if analysis.water.ph > high else ''
    off_text = ''
    if off:
        off_text = (f'◀ {number(analysis.water.ph, 2)}' if off == 'low' else f'{number(analysis.water.ph, 2)} ▶')
        said.append(gettext('off the scale (%(low)s to %(high)s)') % {'low': number(low, 1), 'high': number(high, 1)})
    # each side's word: a border's number AT its border (when the border is on the scale), or what is missing or
    # everywhere on that side, at that end; where they stand is place_names' rule
    co2_word = nh3_word = None
    if co2.everywhere:
        co2_word = ('CO₂', False)
        said.append(gettext('CO₂ is past its limit at every pH'))
    elif co2.ph is not None:
        if left > 0:
            co2_word = (f'CO₂ {number(co2.ph, 2)}', True)
        said.append(gettext('CO₂ passes its limit below pH %(ph)s') % {'ph': number(co2.ph, 2)})
    elif 'co2_limit_mg_l' not in chart.limits:
        co2_word = (gettext('no CO₂ limit'), False)
        said.append(gettext('no CO₂ limit for these fish'))
    else:
        said.append(gettext('CO₂ does not reach its limit'))
    if nh3.everywhere:
        nh3_word = ('NH₃', False)
        said.append(gettext('NH₃ is past its limit at every pH'))
    elif nh3.ph is not None:
        if right < 100:
            nh3_word = (f'{number(nh3.ph, 2)} NH₃', True)
        said.append(gettext('NH₃ passes its limit above pH %(ph)s') % {'ph': number(nh3.ph, 2)})
    elif 'nh3_n_limit_mg_l' not in chart.limits:
        nh3_word = (gettext('no NH₃ limit'), False)
        said.append(gettext('no NH₃ limit for these fish'))
    elif nh3.status == Status.NOT_MEASURED:
        nh3_word = (gettext('no TAN'), False)
        said.append(gettext('NH₃ not assessed: no TAN'))
    else:
        said.append(gettext('NH₃ does not reach its limit'))
    # (review R6) no alkalinity limit row: the stretch between the borders is not drawn safe, and the window says why
    # in words, in the picture where they fit and always in its name
    band = ()
    if analysis.limits.alkalinity_low_mg_l is None or analysis.limits.alkalinity_high_mg_l is None:
        band = (gettext('no alkalinity band'), gettext('no alk. band'))
        said.append(gettext('no alkalinity band for these fish'))
    names = place_names(left, right, None if off else water, co2_word, nh3_word, band, letter_pc(card, view), off_text)
    if chart.old:
        said.append(gettext('last known position, old: %(values)s') % {
            'values': ', '.join(str(parameters.get(item.field).short) for item in chart.old)})
    label = gettext('pH window, %(unit)s: %(said)s') % {'unit': card.unit.code, 'said': '; '.join(said)}
    zones = tuple(key for key, border in (('co2', co2), ('nh3', nh3)) if border.status == Status.CRITICAL)
    return PhWindow(label, tuple(regions), names, _pc(water), zones, bool(chart.old), off=off, off_text=off_text)


# ---- the unit's chart as a picture of the card's own size ---------------------------------------------------------
@dataclass(frozen=True)
class DrawnChart:
    """A card's Deffeyes chart as its template prints it: the picture (farm.water.deffeyes.Picture: shapes and places)
    and every word on and under it, in the reader's language. `refused`: why there is no picture (then `title` and
    `lines` say it in full). `zones`: the regions the core says the water is in ('co2', 'nh3'); `old`: an input is no
    longer fresh, the picture is the last known position. `words`: the one sentence under the picture; `tone` the
    state's shape beside it ('critical', 'blind' for an old picture, 'ok' in the safe zone, '' otherwise)."""
    refused: str = ''
    title: str = ''
    lines: tuple = ()
    picture: object = None
    label: str = ''
    zones: tuple = ()
    old: bool = False
    old_text: str = ''
    words: str = ''
    tone: str = ''
    inputs: str = ''
    notes: tuple = ()        # (text, dy): what the farm has not set, so a region or the safe zone is not drawn
    names: tuple = ()        # (key, text, x, y): what each region is, with the farm's limit
    ph_names: tuple = ()     # (text, x, y)
    x_ticks: tuple = ()      # (text, x, y)
    y_ticks: tuple = ()
    scale: tuple = ()        # the view in words: one or two lines


def arrived(at, now):
    """When a value arrived, as a wall says it: the clock time today, the date and the time before (the farm's zone)."""
    zone = company_zone()
    local, today = timezone.localtime(at, zone), timezone.localtime(now, zone).date()
    if local.date() == today:
        return date_format(local, 'TIME_FORMAT')
    return f"{local:%d.%m} {date_format(local, 'TIME_FORMAT')}"


def _chart_words(chart, analysis, figure):
    """(words, tone) under a chart's picture: where the core says the water is. Nothing is judged here: past a border
    is the core's CRITICAL of that border, and the safe zone is said only when the water lies in the safe region the
    core drew (deffeyes.in_region): the words never differ from the picture."""
    if chart.old:
        return gettext('Last known position · old: %(values)s') % {
            'values': ', '.join(str(parameters.get(item.field).short) for item in chart.old)}, 'blind'
    for key, border, text_ in (('co2', analysis.co2, gettext('In the CO₂ region: %(margin)s pH past the limit')),
                               ('nh3', analysis.nh3, gettext('In the NH₃ region: %(margin)s pH past the limit'))):
        if border.status == Status.CRITICAL:
            if border.margin is None:
                return (gettext('CO₂ is past its limit at every pH') if key == 'co2'
                        else gettext('NH₃ is past its limit at every pH')), 'critical'
            return text_ % {'margin': number(abs(border.margin), 2)}, 'critical'
    if not deffeyes.in_region(figure, 'safe'):
        gaps = deffeyes.safe_zone_gaps(analysis)
        if gaps:
            return gettext('No safe zone: %(why)s') % {'why': str(gaps[0])}, ''
        return gettext('Between the CO₂ and the NH₃ limit, outside the alkalinity band'), ''
    if analysis.co2.margin is not None:
        return gettext('In the safe zone · %(margin)s pH to the CO₂ limit') % {
            'margin': number(abs(analysis.co2.margin), 2)}, 'ok'
    return gettext('In the safe zone'), 'ok'


def chart(card):
    """The DrawnChart of a card: its unit's chart (the chemistry core's analysis and figure) in the card's view
    (card.chart_view: close by the rule of deffeyes.close_window, or full scale in the box the screen's charts of
    this water share, card.chart_extent). Drawn from the LATEST values received (owner decision 1): old inputs are
    said on the picture and under it, never silently. Phase 1: no dosing target is active."""
    made = card.chart
    if card.stock is None:
        # (the design's Big card of an empty unit, the new look's only: shown) the chart is the water against the limits
        # of the fish in it, and there are none: nothing is drawn, and the place says why, once
        return DrawnChart(refused=gettext('No chart: there is no fish in this unit.'))
    if made is None:
        return DrawnChart(refused=gettext('no data'), title=gettext('The chart cannot be drawn'))
    if not isinstance(made, calculation.UnitChart):
        # A water the chemistry core refuses (deffeyes.why_impossible: its own reason) is not a missing value.
        first = (gettext('Not worked out: %(why)s.') if made.impossible else gettext('Missing: %(why)s.')) % {
            'why': _refused(made)}
        return DrawnChart(refused=_refused(made), title=gettext('The chart cannot be drawn'),
                          lines=(first,
                                 gettext('Nothing is assumed for a missing value.')))
    analysis = made.calculation.analysis
    view = card.chart_view
    figure = deffeyes.card_figure(analysis, card.chart_extent if view == deffeyes.FULL else ())
    per_meq = deffeyes.chemistry.MG_CACO3_PER_MEQ
    low, top = analysis.limits.alkalinity_low_mg_l, analysis.limits.alkalinity_high_mg_l
    band = (None if low is None else low / per_meq, None if top is None else top / per_meq)
    window = deffeyes.window_of(figure, view, band)
    picture = deffeyes.picture(figure, window, view)
    words, tone = _chart_words(made, analysis, figure)
    limits = analysis.limits
    region = {
        'co2': '' if limits.co2_mg_l is None else gettext('CO₂ > %(limit)s mg/L') % {
            'limit': deffeyes.shown(limits.co2_mg_l, 1)},
        'nh3': '' if limits.nh3_n_mg_l is None else gettext('NH₃-N > %(limit)s mg/L') % {
            'limit': deffeyes.shown(limits.nh3_n_mg_l, 4)},
        'safe': gettext('safe'),
    }
    names = tuple((key, region[key], x, y) for key, (x, y) in picture.names.items() if region[key])
    if window.full and view == deffeyes.CLOSE:
        scale = (gettext('the close view is the full scale here: the water is far past a limit'),)
    elif window.full:
        scale = (gettext('full scale · axes from zero'),)
    else:
        scale = (gettext('close view · ×%(zoom)s') % {'zoom': number(window.zoom, 1)},
                 gettext('this card’s own scale'))
    # what is NOT in the picture, and why: a region or the safe zone the farm's limits do not give is said, never left
    # as an empty side that reads as safe
    missing = []
    if 'co2_limit_mg_l' not in made.limits:
        missing.append(gettext('no CO₂ limit for these fish'))
    if 'nh3_n_limit_mg_l' not in made.limits:
        missing.append(gettext('no NH₃ limit for these fish'))
    elif analysis.nh3.status == Status.NOT_MEASURED:
        missing.append(gettext('NH₃ not assessed: no TAN'))
    if low is None or top is None:
        missing.append(gettext('no alkalinity band for these fish'))
    # In the text's own em (its font is .8 of the picture's, static/css/monitor.css): in the close view the first note
    # stands under the locator, whose box ends 3.4 of the picture's em down (_chart.html), so its letters start below
    # it (at 4.45 they crossed the box's lower edge on every wall).
    first = 5.3 if not window.full else 2.7
    notes = tuple((text_, f'{first + 1.35 * index:.2f}em') for index, text_ in enumerate(missing))
    said = []
    for item in made.inputs:
        if item.field not in calculation.REQUIRED:
            continue
        short = str(parameters.get(item.field).short)
        said.append(gettext('%(value)s assumed') % {'value': short} if item.assumed or item.reading is None
                    else f'{short} {arrived(item.reading.at, card.now)}')
    label = gettext('Deffeyes chart, %(unit)s: %(words)s; pH %(ph)s, alkalinity %(alkalinity)s mg/L, DIC %(dic)s '
                    'mmol/L, calculated CO₂ %(co2)s mg/L; %(view)s') % {
        'unit': card.unit.code, 'words': words, 'ph': number(analysis.water.ph, 2),
        'alkalinity': number(analysis.water.alkalinity_mg_l, 0), 'dic': number(analysis.dic, 2),
        'co2': number(analysis.co2_mg_l, 1), 'view': scale[0]}
    return DrawnChart(
        picture=picture, label=label, words=words, tone=tone,
        zones=tuple(key for key, border in (('co2', analysis.co2), ('nh3', analysis.nh3))
                    if border.status == Status.CRITICAL),
        old=bool(made.old), old_text=gettext('last known position'),
        inputs=gettext('inputs: %(list)s') % {'list': ' · '.join(said)}, notes=notes, names=names,
        ph_names=tuple((gettext('pH %(ph)s') % {'ph': number(ph, decimals)}, x, y)
                       for ph, decimals, x, y in picture.ph_names),
        x_ticks=tuple((number(dic, decimals), x, y) for dic, decimals, x, y in picture.x_ticks),
        y_ticks=tuple((str(mg), x, y) for mg, x, y in picture.y_ticks), scale=scale)


# ---- every value of the middle point, a row each ---------------------------------------------------------------------
@dataclass(frozen=True)
class WaterRow:
    """One value of the card's water as a row: what it is and its figure (`said`, a Face), the strip against the limit
    row that judged it (`bar`, None without a limit), where it came from in words, and when it arrived: the clock
    time today, the day and month before, with its age."""
    said: Face
    bar: object
    arrived: str
    alert: str


# The reasons a fitted card shows (templates/monitoring/_card_fit.html), one rule for every size of card: an ALERT, a
# reason of a critical, warning or no-recent-data card, is never folded away while the card holds it, and what it cannot
# hold is said in words in the card's tone ("3 more alerts, see the band" on a Big card, "7 more alerts" on a Small
# one), never a bare "+N" and never hidden silently; NOTES (no limit, a note) fold into "+N", whole in its title, for a
# screen reader and in the band's chips (a unit with ten values no limit judges said ten lines and pushed its water and
# boxes out of the card). The coordinator's rules of 2026-11-27 and -28: a critical or a warning is never folded away
# where nobody can hover, and a Small card never hides that there are more.
# HOLDS, (alerts, notes) by the card's size: a Big card drawn at the size of its place (the pane, a wall; on the desk
# it flows and shows every one) FIT_ALERTS and FIT_NOTES; a Small card's one line the worst one. FIT_ALERTS is measured,
# not guessed: each line of reasons takes its share from every row of the card's grid, and the first to run out of its
# place is a value's tile; with TW-15's eight criticals six lines and the notice overflow the tiles at 4K in the pane
# and on a wall (by 0.01 to 0.05 of a line), five fit on every surface in the three languages (the browser test,
# frontend/test/monitoring.pages.ts: the pane at 1440, 1920 and 3840 px, the walls at 1080p and 4K).
FIT_NOTES = 3
FIT_ALERTS = 5
HOLDS = {'big': (FIT_ALERTS, FIT_NOTES), 'small': (1, 1)}
ALERT_STATES = frozenset({'critical', 'warning', 'blind'})


@dataclass(frozen=True)
class Folded:
    """What a fitted card shows of its state's reasons: the first `shown`, and `rest` folded; `alerts`: they are alerts
    (the card's state is critical, a warning or no recent data), said in words when folded."""
    shown: int
    rest: tuple
    alerts: bool


def fold(state, size='big'):
    """The Folded of a card's state on a card of that size ('big' or 'small': HOLDS)."""
    alerts = state.key in ALERT_STATES
    shown = HOLDS[size][0 if alerts else 1]
    return Folded(shown, tuple(state.reasons[shown:]), alerts)


# More rows than this stand in two columns where two fit side by side (the water's rows_units): a row is never lower
# than a line of the card's small text.
WATER_ROWS = 14
# At most this many values of a full-height card's water are the design's tiles in the new look: the catalogue's lines of
# tiles, each of so many (catalogue water_table tiles), stated there once.
WATER_TILES = catalogue.WIDGETS['water_table'].tiles[0] * catalogue.WIDGETS['water_table'].tiles[1]
# Between two columns of rows, in card units (the template's gap-x-8: two units).
ROWS_GAP = 2.0


def water_rows(card, view=None):
    """((WaterRow, ...), ...): every value of the card's middle point in one column of rows, or in two when there are
    more than WATER_ROWS AND the widget's place on the card holds two columns of rows side by side (the water's
    catalogue rows_units, measured as the validator measures a place: two columns were set whatever the place's width,
    and on a Big card their cells lay over each other: review 2, N1); () when the unit has no middle point or it has no
    value."""
    water = card.middle_water
    if water is None:
        return ()
    rows = []
    for reading in water.readings.values():
        said = face(reading, card.now)
        rows.append(WaterRow(said, bar(said), arrived(reading.at, card.now), alert_of(said.status)))
    if not rows:
        return ()
    per = (len(rows) + 1) // 2 if columns_for(card, view, len(rows)) == 2 else len(rows)
    return tuple(tuple(rows[start:start + per]) for start in range(0, len(rows), per))


def columns_for(card, view, count):
    """1 or 2: the columns of rows `count` values stand in on the card: two only for more than WATER_ROWS of them and
    where the widget's place holds two columns side by side (the water's catalogue rows_units, and the gap between)."""
    wide = 2 * catalogue.WIDGETS['water_table'].rows_units + ROWS_GAP
    return 2 if count > WATER_ROWS and _place(card, view)[0] >= wide else 1


def _place(card, view):
    """(width, height) in card units of a widget's place on a fitted card (validate.fitted_place), or (0, 0) when the
    card flows or the widget is not on its template."""
    template = card.template
    widget = None if view is None else next((each for each in template.layout['widgets'] if each['id'] == view.id), None)
    if widget is None or not template.measure:
        return 0.0, 0.0
    from .validate import fitted_place
    return fitted_place(widget, template.rows, template.measure)


def tiled(card, view, columns):
    """How many of the design's tiles a full-height card's water (`columns`: water_rows') stands in to a line, or 0 for
    a row a value: ONE column of at most WATER_TILES values, on a full-height card whose template gives the water a
    place that holds the catalogue's lines of tiles (the water's tiles and tile_units, measured as the validator
    measures a place: validate.fitted_place). The server's one answer, said on the rows' frame (`data-tiles="4"`, in
    both looks: the classic sheet reads nothing of it), which the new look's sheet draws for that count only
    (static/css/monitor-next.css): a count it has no rule for is drawn as rows, never as tiles of another width."""
    spec = catalogue.WIDGETS['water_table']
    if not card.template.fill or len(columns) != 1 or len(columns[0]) > WATER_TILES:
        return 0
    (per, lines), (wide, high) = spec.tiles, spec.tile_units
    place = _place(card, view)
    return per if place[0] >= per * wide and place[1] >= lines * high else 0


# What a card says of each of the unit's other sampling points.
POINT_VALUES = (parameters.OXYGEN_MG_L, parameters.TEMPERATURE, parameters.PH)


def other_points(card):
    """((name, (Face, Face, Face), oldest), ...): the unit's sampling points other than its middle one, each with its
    oxygen, temperature and pH as a card says a value, and the Face of the OLDEST of them (None when it has none): a
    point's age said once, never fresher than any of its values (the new look's box, where three ages do not fit beside
    a point's name: review 2, N2)."""
    found = []
    for water in card.water:
        if water.point is None or water.point.kind == water_read.MIDDLE:
            continue
        faces = tuple(face(water.get(code), card.now, parameters.get(code)) for code in POINT_VALUES)
        said = [each for each in faces if not each.missing]
        found.append((water.point.name, faces, min(said, key=lambda each: each.reading.at) if said else None))
    return tuple(found)


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

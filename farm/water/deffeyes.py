"""The Water Quality Management Chart: a Deffeyes diagram (Deffeyes 1965, Limnol. Oceanogr. 10: 412) of a
water, its alkalinity against its dissolved inorganic carbon, with the lines of equal pH, the regions where
CO₂, NH₃ and H₂S exceed their limits, the safe region, the calcite and aragonite saturation lines and the
water's point. Ported from the source's calculator (/sites/water-chemistry, the Calculator tab:
libs/aquaculture-engines/src/water-chemistry/deffeyes-data.ts, web/shared-ui/src/water-chemistry/compute.ts
and components/DeffeyesChart.tsx); the chemistry is farm/water/chemistry.py. Pure Python, no database:
`analyse` works out the values of a water (`Water`, what a sample holds) against `Limits` and an optional
`Target`, `geometry` lays the chart out in the chart's own units, and `draw` turns it into the SVG that
templates/farm/_deffeyes_chart.html shows, server-rendered, without JavaScript.

The calculator (Operations › Water chemistry › Calculator) fills `Water`, `Limits` and `Target` from its
form; a unit's own chart (calculation.chart_of, the monitoring cards' window) fills `Water` from its latest
readings and `Limits` from the water limits of its fish, through the same `calculation.inputs_from`; nothing
here changes for either (README, Water chemistry).

What the chart shows, as the source draws it (the corrections are in the bug document, WQ-30 to WQ-39):
- Axes: DIC (mmol/L) across, alkalinity (meq/L) up, 0 to 6 each; wider when the water's point, the
  target or the alkalinity band lies beyond (WQ-33).
- pH isolines every 0.25 from 4.25 to 12.5, straight lines (chemistry.Equilibria.isoline); those every
  0.5 from 5.0 to 12.0 stronger and labelled.
- NH₃ toxic: above the isoline of the pH where the TAN gives the NH₃-N limit. H₂S toxic: below the
  isoline of the pH where the total sulfide gives the H₂S limit. CO₂ toxic: below (right of) the curve
  where CO₂ equals the limit, DIC α0 = c. Each is shaded, its boundary dashed.
- The safe zone: the alkalinity band (low to high) between the NH₃ isoline and the CO₂ curve or the H₂S
  isoline, whichever is the higher pH (WQ-30). A missing value is never taken for a safe one: without the
  TAN, the NH₃ limit or the CO₂ limit, or with a total sulfide but no H₂S limit, there is no safe zone and a
  note says what is missing; without a total sulfide the zone is drawn and named "H₂S not assessed".
- Ω = 1 for calcite and aragonite (Mucci 1983) for the calcium given, in water of 5 to 44 ‰ (WQ-32).
- The water (a star) and the target (a cross), a dashed line between them.
- A limit's status follows the source: past its pH border critical, within 0.2 pH of it a warning. A
  border outside the chart's pH range (4 to 12.5) is said in words, not as a number (WQ-34); its region is
  still shaded wherever it meets the plotted box, which in a large box can reach past pH 12.5 or below 4.
- Dosing (farm/water/dosing.py, as `dosing.Visual`): one reagent chosen, its direction line from the water;
  two, both lines, the wedge between them and their path to the target through the waypoint. The simulator:
  the water after each amount, joined from the water, an arrowhead at each step. The axes grow to hold the
  waypoint and every step."""
import math
from dataclasses import asdict, dataclass, field
from decimal import Decimal

from django.utils import formats
from django.utils.translation import gettext_lazy as _

from . import chemistry, messages, native
from .evaluate import Status

PH_RANGE = native.PH_RANGE                                   # the chart's pH domain (the source's), 4 to 12.5
AXIS = native.AXIS            # the axes' ends at least: 6 mmol/L DIC and 6 meq/L alkalinity
ALERT_PH = native.ALERT_PH    # a pH border nearer than this (0.2) is a warning

LAYERS = [
    ('isolines', _('pH isolines')),
    ('safe', _('Safe zone')),
    ('nh3', _('NH₃ toxic')),
    ('co2', _('CO₂ toxic')),
    ('h2s', _('H₂S toxic')),
    ('omega', _('Ω calcite and aragonite')),
    ('target', _('Target')),
    ('dosing', _('Dosing path')),
    ('simulator', _('Simulator path')),
]
ALL_LAYERS = frozenset(key for key, _label in LAYERS)


# ---- what goes in ----------------------------------------------------------------------------------------
@dataclass(frozen=True)
class Water:
    """The water the chart is drawn for: what a sample holds. Units and bases are in the names; total
    sulfide is as S."""
    temperature_c: float
    salinity_ppt: float
    ph: float
    alkalinity_mg_l: float
    tan_mg_l: float | None = None
    total_sulfide_ug_l: float | None = None
    calcium_mg_l: float | None = None
    oxygen_mg_l: float | None = None


@dataclass(frozen=True)
class Limits:
    """The values not to pass: NH₃-N in mg/L as N, CO₂ in mg/L, H₂S in µg/L as H₂S; and the alkalinity band
    the safe zone lies in, mg/L as CaCO₃. Any of them may be missing."""
    nh3_n_mg_l: float | None = None
    co2_mg_l: float | None = None
    h2s_ug_l: float | None = None
    alkalinity_low_mg_l: float | None = None
    alkalinity_high_mg_l: float | None = None


@dataclass(frozen=True)
class Target:
    ph: float
    alkalinity_mg_l: float


# ---- what comes out ----------------------------------------------------------------------------------------
@dataclass(frozen=True)
class Border:
    """A limit as a pH: toxic above `ph` (NH₃) or below it (CO₂, H₂S); `ph` None when the limit cannot be
    reached. `margin` is how far the water's pH is from it on the safe side (negative: past it). Where it lies
    against the chart's pH range (4 to 12.5), as the core judged it: `on_chart` (shown as a number), `everywhere`
    (passed at every pH of the range), `off_chart` (not reached in the range)."""
    ph: float | None
    toxic_above: bool
    margin: float | None
    status: str
    on_chart: bool = False
    everywhere: bool = False
    off_chart: bool = False


def _border(found):
    return Border(found['ph'], found['toxic_above'], found['margin'], Status(found['status']), found['on_chart'],
                  found['everywhere'], found['off_chart'])


def judge(ph, border, toxic_above, missing=None):
    """The border and the status (the core's rule: critical past it, a warning within ALERT_PH of it, ok short of it or
    when it cannot be reached). `missing`: the status when there is nothing to judge (no value or no limit)."""
    return _border(native.judge(ph, border, toxic_above, None if missing is None else Status(missing).value))


@dataclass(frozen=True)
class Analysis:
    """The values of a water, worked out: concentrations per litre, alkalinity in meq/L, DIC in mmol/L."""
    water: Water
    limits: Limits
    target: Target | None
    equilibria: chemistry.Equilibria
    alkalinity_meq: float
    dic: float
    co2_mg_l: float
    co2: Border
    target_alkalinity_meq: float | None
    target_dic: float | None
    target_co2_mg_l: float | None
    nh3_n_mg_l: float | None
    nh3: Border
    safe_tan_mg_l: float | None              # the TAN that gives the NH₃-N limit at this pH
    nh3_share_at_border_pct: float | None    # NH₃ as a share of TAN at the border, limit ÷ TAN
    h2s_ug_l: float | None                   # as H₂S
    h2s: Border
    safe_total_sulfide_ug_l: float | None    # as S: the total sulfide that gives the H₂S limit at this pH
    oxygen_solubility_mg_l: float
    oxygen_saturation_pct: float | None
    pressure_atm: float

    nh3_share_pct: float                     # NH₃ as a share of TAN at the water's pH, %
    h2s_share_pct: float                     # H₂S as a share of the total sulfide at the water's pH, %


def analyse(water, limits=Limits(), target=None, pressure=1.0):
    """The values of a water against the limits (the core's analysis, chemcore/core/src/analysis.rs): DIC and CO₂ from
    the alkalinity and the pH, NH₃-N from the TAN, H₂S from the total sulfide, each limit as a pH border, the oxygen
    saturation at `pressure` (atm)."""
    found = native.analyse(
        **asdict(water), **asdict(limits), target_ph=None if target is None else target.ph,
        target_alkalinity_mg_l=None if target is None else target.alkalinity_mg_l, pressure=pressure)
    for key in ('co2', 'nh3', 'h2s'):
        found[key] = _border(found[key])
    return Analysis(water=water, limits=limits, target=target, **found)


def alkalinity_floor(temperature_c, salinity_ppt, ph):
    """The alkalinity (mg/L as CaCO₃) a water of this pH has at least: hydroxide and borate are alkalinity too, so at a
    high pH the alkalinity has a floor, below which the DIC would be negative."""
    return native.alkalinity_floor(temperature_c, salinity_ppt, ph)


def why_impossible(temperature_c, salinity_ppt, ph, alkalinity_mg_l):
    """Why a water of this pH and alkalinity cannot be (its alkalinity at or below the floor of `alkalinity_floor`),
    in the active language; '' when it can. The calculator's form and a unit's chart ask here."""
    floor = native.why_impossible(temperature_c, salinity_ppt, ph, alkalinity_mg_l)
    if floor is None:
        return ''
    return str(_('At this pH the alkalinity is above %(floor)s mg/L as CaCO₃: the hydroxide and borate alone are '
                 'that much.') % {'floor': shown(floor, 1)})


def possible(temperature_c, salinity_ppt, ph, alkalinity_mg_l):
    """Whether a water of this pH and alkalinity can be (`why_impossible` has nothing to say)."""
    return not why_impossible(temperature_c, salinity_ppt, ph, alkalinity_mg_l)


# ---- the chart in its own units: DIC (mmol/L) across, alkalinity (meq/L) up --------------------------------
@dataclass(frozen=True)
class Box:
    """The axes' ends and their tick steps."""
    dic: float
    alkalinity: float
    dic_step: float
    alkalinity_step: float

    def corners(self):
        return [(0.0, 0.0), (self.dic, 0.0), (self.dic, self.alkalinity), (0.0, self.alkalinity)]

    def inside(self, point, slack=1e-9):
        x, y = point
        return -slack <= x <= self.dic + slack and -slack <= y <= self.alkalinity + slack


def box_of(analysis, extra=()):
    """The box that holds the water, the target, the alkalinity band and the `extra` points (DIC, alkalinity) with
    10 % to spare (the core's 1-2-5 steps; native.ChartTooLargeError beyond 12 steps of 5e7)."""
    target = None if analysis.target_dic is None else (analysis.target_dic, analysis.target_alkalinity_meq)
    return Box(*native.box_of(analysis.dic, analysis.alkalinity_meq, target, analysis.limits.alkalinity_high_mg_l,
                              [tuple(point) for point in extra]))


@dataclass(frozen=True)
class Isoline:
    ph: float
    labelled: bool
    segment: tuple           # its two ends inside the box


@dataclass
class Geometry:
    """The chart in DIC (mmol/L) and alkalinity (meq/L): what `draw` maps to the SVG."""
    box: Box
    isolines: list = field(default_factory=list)
    regions: dict = field(default_factory=dict)        # layer → polygon
    boundaries: dict = field(default_factory=dict)     # layer → [polyline]
    omega: dict = field(default_factory=dict)          # 'calcite' / 'aragonite' → [polyline]
    point: tuple = (0.0, 0.0)
    target: tuple | None = None
    reagent_lines: list = field(default_factory=list)  # [(reagent, [polyline])]
    wedge: list = field(default_factory=list)          # polygon
    dosing_path: list = field(default_factory=list)    # [polyline]
    waypoint: tuple | None = None
    simulator: list = field(default_factory=list)      # [(DIC, alkalinity)] of every step, the water first
    notes: list = field(default_factory=list)


def _inputs(analysis):
    """What the core needs of an analysis: its water and limits as dicts, its target as (pH, alkalinity), its pressure."""
    target = analysis.target
    return (asdict(analysis.water), asdict(analysis.limits),
            None if target is None else (target.ph, target.alkalinity_mg_l), analysis.pressure_atm)


def safe_zone_gaps(analysis):
    """Why there can be no safe zone, as notes (the core's codes, said by farm/water/messages.py): a missing value is
    never taken for a safe one. Every limit the zone is bounded by must be judged: the TAN and its NH₃ limit, the CO₂
    limit, the alkalinity band, and an H₂S limit when a total sulfide is given. A water without a total sulfide is not
    a gap: its zone is drawn, named "H₂S not assessed"."""
    water, limits, target, pressure = _inputs(analysis)
    return [messages.note(code) for code in native.safe_zone_gaps(water, limits, target, pressure)]


def h2s_assessed(analysis):
    """Whether the safe zone takes H₂S into account: a total sulfide was given."""
    return analysis.h2s.status != Status.NOT_MEASURED


def safe_zone(analysis, box):
    """The safe region in a box (the core's): the alkalinity band, from the NH₃ isoline (the highest pH allowed; the
    chart's top pH when the TAN cannot reach its limit) to the CO₂ curve or the H₂S isoline, whichever is the higher pH.
    [] when a value or a limit it needs is missing (safe_zone_gaps), or when the band has no safe pH."""
    water, limits, target, pressure = _inputs(analysis)
    return native.safe_zone(water, limits, (box.dic, box.alkalinity, box.dic_step, box.alkalinity_step), target, pressure)


def geometry(analysis, layers=ALL_LAYERS, dosing=None, simulator=(), extent=()):
    """The chart of an analysis, the layers asked for, in the chart's units (the core's,
    chemcore/core/src/geometry.rs); a note says why a layer asked for is not drawn. `dosing`: the dosing layer (a
    dosing.Visual); `simulator`: the water after each step of the simulator, (DIC, alkalinity), the water first;
    `extent`: more points (DIC, alkalinity) the box must hold, drawn as nothing (a replay's frames, A6)."""
    water, limits, target, pressure = _inputs(analysis)
    drawn = None if dosing is None else {
        'lines': [(reagent.key, line) for reagent, line in dosing.lines], 'wedge': list(dosing.wedge or []),
        'path': list(dosing.path or []), 'waypoint': dosing.waypoint}
    found = native.geometry(water, limits, target, pressure, sorted(layers), drawn,
                            [tuple(point) for point in simulator], [tuple(point) for point in extent])
    reagents = {} if dosing is None else {reagent.key: reagent for reagent, _line in dosing.lines}
    shape = Geometry(
        Box(*found['box']), isolines=[Isoline(ph, labelled, segment) for ph, labelled, segment in found['isolines']],
        regions=found['regions'], boundaries=found['boundaries'], omega=found['omega'], point=found['point'],
        target=found['target'], reagent_lines=[(reagents[key], lines) for key, lines in found['reagent_lines']],
        wedge=found['wedge'], dosing_path=found['dosing_path'], waypoint=found['waypoint'],
        simulator=found['simulator'], notes=[messages.note(code) for code in found['notes']])
    if dosing is not None and 'dosing' in layers and dosing.note:
        shape.notes.append(dosing.note)
    return shape


# ---- the SVG --------------------------------------------------------------------------------------------
WIDTH, HEIGHT = 600, 600
LEFT, TOP, PLOT = 64, 16, 520                 # the plot is a square of PLOT px
LABEL_AT = 0.52                               # an isoline's label sits this far along it (the source's)
# The isolines' colours, the source's sequential ramp (shared-contracts domainScale.sequential, read by
# phIsolineColor in deffeyes-data.ts): one step per half pH unit from 5.5, red to deep purple; below pH 6.0
# the first, from 10.0 up the last.
RAMP = ['#DC2626', '#EF4444', '#F97316', '#EAB308', '#22C55E', '#06B6D4', '#3B82F6', '#6366F1', '#A855F7',
        '#7C3AED']


def isoline_colour(ph):
    return RAMP[min(len(RAMP) - 1, max(0, math.floor((ph - 5.5) / 0.5)))]


def _fixed(value):
    return f'{value:.2f}'


@dataclass
class Chart:
    """The SVG's parts in pixels, every coordinate a string with a dot decimal whatever the language: the
    template prints them as they are."""
    width: int
    height: int
    plot: dict
    x_ticks: list
    y_ticks: list
    isolines: list
    regions: list
    boundaries: list
    omega: list
    legend: list
    point: dict
    target: dict | None
    path: str | None
    notes: list
    box: Box
    reagent_lines: list = field(default_factory=list)
    wedge: str | None = None
    dosing_path: list = field(default_factory=list)
    waypoint: dict | None = None
    simulator: dict | None = None


def _flat(polyline):
    return [float(value) for point in polyline for value in point]


def _pairs(values):
    return [(values[index], values[index + 1]) for index in range(0, len(values), 2)]


def figure(analysis, shape):
    """A chart's whole geometry (`geometry`) as numbers and words a JSON document holds: THE shape the server's SVG
    (`render`) and the replay's player draw from (A8). Every line a flat array [DIC, alkalinity, DIC, alkalinity, ...]
    in the chart's units; the regions and borders with their names and the notes in the active language."""
    box = shape.box
    names = _region_names(analysis)
    return {
        'box': [float(box.dic), float(box.alkalinity), float(box.dic_step), float(box.alkalinity_step)],
        'isolines': [[float(isoline.ph), int(isoline.labelled), *_flat(isoline.segment)] for isoline in shape.isolines],
        'regions': [[key, names[key], _flat(polygon)]
                    for key in ('co2', 'h2s', 'nh3', 'safe') if (polygon := shape.regions.get(key))],
        'boundaries': [[key, names[key], _flat(line)] for key in ('co2', 'h2s', 'nh3')
                       for line in shape.boundaries.get(key, [])],
        'omega': [[key, _flat(line)] for key in ('calcite', 'aragonite') for line in shape.omega.get(key, [])],
        'point': [float(shape.point[0]), float(shape.point[1])],
        'target': None if shape.target is None else [float(shape.target[0]), float(shape.target[1])],
        'reagent_lines': [[reagent.key, reagent.formula, _flat(line)]
                          for reagent, lines in shape.reagent_lines for line in lines],
        'wedge': _flat(shape.wedge),
        'dosing_path': [_flat(line) for line in shape.dosing_path],
        'waypoint': None if shape.waypoint is None else [float(shape.waypoint[0]), float(shape.waypoint[1])],
        'simulator': _flat(shape.simulator),
        'notes': [str(note) for note in shape.notes],
    }


def draw(analysis, layers=ALL_LAYERS, dosing=None, simulator=(), extent=()):
    """The chart of an analysis as the template draws it (`dosing`, `simulator` and `extent` as `geometry` takes them):
    the SVG's parts drawn from its figure."""
    return render(figure(analysis, geometry(analysis, layers, dosing, simulator, extent)))


def render(figure):
    """The SVG's parts (Chart) of a figure, from the figure alone: the server draws every chart through here, and the
    replay's player draws the same figures."""
    box = Box(*figure['box'])

    def x(dic):
        return LEFT + dic / box.dic * PLOT

    def y(alkalinity):
        return TOP + PLOT - alkalinity / box.alkalinity * PLOT

    def points(flat):
        return ' '.join(f'{_fixed(x(dic))},{_fixed(y(alkalinity))}' for dic, alkalinity in _pairs(flat))

    def ticks(end, step, place):
        return [{'at': _fixed(place(step * index)), 'label': _tick(step * index)}
                for index in range(round(end / step) + 1)]

    isolines = []
    for ph, labelled, *segment in figure['isolines']:
        (x1, y1), (x2, y2) = [(x(dic), y(alkalinity)) for dic, alkalinity in _pairs(segment)]
        label = None
        if labelled:
            angle = max(-65.0, min(65.0, math.degrees(math.atan2(y2 - y1, x2 - x1))))
            label = {'x': _fixed(x1 + LABEL_AT * (x2 - x1)), 'y': _fixed(y1 + LABEL_AT * (y2 - y1)),
                     'angle': _fixed(angle),
                     'text': f'pH {formats.number_format(Decimal(f"{ph:.1f}"), 1, use_l10n=True)}'}
        isolines.append({'ph': f'{ph:.2f}', 'labelled': bool(labelled),
                         'colour': isoline_colour(ph), 'points': points(segment), 'label': label})
    regions = [{'key': key, 'name': name, 'points': points(polygon)} for key, name, polygon in figure['regions']]
    boundaries = [{'key': key, 'name': name, 'points': points(line)} for key, name, line in figure['boundaries']]
    omega_names = {'calcite': _('Ω calcite = 1'), 'aragonite': _('Ω aragonite = 1')}
    omega = [{'key': key, 'name': omega_names[key], 'points': points(line)} for key, line in figure['omega']]
    legend = [{'key': region['key'], 'name': region['name']} for region in regions]
    legend += [{'key': key, 'name': omega_names[key]} for key in ('calcite', 'aragonite')
               if any(each == key for each, _line in figure['omega'])]
    px, py = x(figure['point'][0]), y(figure['point'][1])
    target = path = None
    if figure['target'] is not None:
        tx, ty = x(figure['target'][0]), y(figure['target'][1])
        arm = 7
        target = {'x': _fixed(tx), 'y': _fixed(ty),
                  'lines': [[_fixed(tx - arm), _fixed(ty - arm), _fixed(tx + arm), _fixed(ty + arm)],
                            [_fixed(tx + arm), _fixed(ty - arm), _fixed(tx - arm), _fixed(ty + arm)]]}
        path = points([*figure['point'], *figure['target']])
    reagent_lines = []
    for key, formula, line in figure['reagent_lines']:
        (x1, y1), (x2, y2) = [(x(dic), y(alkalinity)) for dic, alkalinity in _pairs(line)[-2:]]
        reagent_lines.append({'key': key, 'formula': formula, 'points': points(line), 'arrow': _arrow(x1, y1, x2, y2)})
    simulator_drawing = None
    if figure['simulator']:
        pixels = [(x(dic), y(alkalinity)) for dic, alkalinity in _pairs(figure['simulator'])]
        simulator_drawing = {
            'points': ' '.join(f'{_fixed(across)},{_fixed(up)}' for across, up in pixels),
            'arrows': [_arrow(*pixels[index - 1], *pixels[index]) for index in range(1, len(pixels))
                       if math.dist(pixels[index - 1], pixels[index]) > 1],
            'end': {'x': _fixed(pixels[-1][0]), 'y': _fixed(pixels[-1][1])}}
    waypoint = None
    if figure['waypoint'] is not None and box.inside(tuple(figure['waypoint'])):
        waypoint = {'x': _fixed(x(figure['waypoint'][0])), 'y': _fixed(y(figure['waypoint'][1]))}
    return Chart(
        width=WIDTH, height=HEIGHT,
        plot={'left': LEFT, 'top': TOP, 'right': LEFT + PLOT, 'bottom': TOP + PLOT, 'size': PLOT,
              'centre_x': LEFT + PLOT // 2, 'centre_y': TOP + PLOT // 2, 'x_tick_y': TOP + PLOT + 18,
              'y_tick_x': LEFT - 8, 'x_title_y': HEIGHT - 10, 'y_title_x': 16},
        x_ticks=ticks(box.dic, box.dic_step, x), y_ticks=ticks(box.alkalinity, box.alkalinity_step, y),
        isolines=isolines, regions=regions, boundaries=boundaries, omega=omega, legend=legend,
        point={'x': _fixed(px), 'y': _fixed(py), 'star': _star(px, py)}, target=target, path=path,
        notes=list(figure['notes']), box=box, reagent_lines=reagent_lines,
        wedge=points(figure['wedge']) if figure['wedge'] else None,
        dosing_path=[points(line) for line in figure['dosing_path']], waypoint=waypoint, simulator=simulator_drawing)


def _arrow(x1, y1, x2, y2, size=9):
    """An arrowhead at (x2, y2) pointing away from (x1, y1), in pixels (the source's, 0.8 π either side)."""
    angle = math.atan2(y2 - y1, x2 - x1)
    corners = [(x2, y2)] + [(x2 + size * math.cos(angle + turn), y2 + size * math.sin(angle + turn))
                            for turn in (math.pi * 0.8, -math.pi * 0.8)]
    return ' '.join(f'{_fixed(a)},{_fixed(b)}' for a, b in corners)


def _tick(value):
    return f'{value:g}'


def _star(cx, cy, radius=8):
    """A five-pointed star around a point (the source's current-point marker)."""
    corners = []
    for index in range(5):
        for angle, reach in ((index * 72 - 90, radius), (index * 72 + 36 - 90, radius * 0.4)):
            corners.append(f'{_fixed(cx + reach * math.cos(math.radians(angle)))},'
                           f'{_fixed(cy + reach * math.sin(math.radians(angle)))}')
    return ' '.join(corners)


def shown(value, decimals):
    """A number as the language writes it, at most `decimals` decimals, no trailing zeros: 8,42; 15."""
    rounded = Decimal(repr(float(value))).quantize(Decimal(1).scaleb(-decimals))
    rounded = rounded.to_integral() if rounded == rounded.to_integral() else rounded.normalize()
    return formats.number_format(rounded, use_l10n=True)


def _ph(value):
    """A pH border at two decimals, as the language writes it: 8.40, 8,40."""
    return formats.number_format(Decimal(f'{value:.2f}'), 2, use_l10n=True)


def _region_names(analysis):
    """The regions' names with their borders, as the source labels them: NH₃ toxic (pH > 8.42)."""
    names = {'safe': str(_('Safe zone') if h2s_assessed(analysis) else _('Safe zone (H₂S not assessed)'))}
    if analysis.nh3.everywhere:
        names['nh3'] = str(_('NH₃ toxic (at every pH of the chart)'))
    elif analysis.nh3.ph is not None:
        names['nh3'] = str(_('NH₃ toxic (pH > %(ph)s)') % {'ph': _ph(analysis.nh3.ph)})
    if analysis.limits.co2_mg_l is not None:
        names['co2'] = str(_('CO₂ toxic (> %(limit)s mg/L)') % {'limit': shown(analysis.limits.co2_mg_l, 1)})
    if analysis.h2s.everywhere:
        names['h2s'] = str(_('H₂S toxic (at every pH of the chart)'))
    elif analysis.h2s.ph is not None:
        names['h2s'] = str(_('H₂S toxic (pH < %(ph)s)') % {'ph': _ph(analysis.h2s.ph)})
    return names


# ---- the card's picture: a window on the figure, close or at full scale ----------------------------------------
# A monitoring card draws the same figure (`figure`) in a box of any shape, in one of TWO VIEWS (owner decision 12,
# 2026-11-12), each a window on the core's figure and nothing else:
#   FULL   the core's own box, from the origin;
#   CLOSE  the window `close_window` works out by the rule below.
# `picture` turns the figure and a window into the parts templates/monitoring/widgets/_chart.html prints: the outer
# <svg> has NO viewBox (its text is the card's own text size), the shapes sit in a nested <svg viewBox="0 0 1000 1000"
# preserveAspectRatio="none"> stretched over the plot, and every label and mark is placed by a percentage, so the plot
# need not be square. No style attribute anywhere (the Content-Security-Policy is style-src 'self'). Every coordinate
# is a string with a dot decimal whatever the language.
CLOSE, FULL = 'close', 'full'
VIEWS = (CLOSE, FULL)
# The layers a card's picture draws: the lines of equal pH, the two toxic regions with their borders, the safe zone
# and the target. (H₂S, Ω, the dosing and simulator paths are the calculator's.)
CARD_LAYERS = frozenset({'isolines', 'safe', 'nh3', 'co2', 'target'})
# The rule of CLOSE, in numbers: the window is never narrower than CLOSE_MIN mmol/L (under that the last digit of a pH
# probe fills the picture); what must be seen across is the middle CLOSE_SHARE of it; what must be seen up and down
# takes at most CLOSE_UP of its height; a window of CLOSE_FULL of the core's box or more IS the box.
CLOSE_MIN, CLOSE_SHARE, CLOSE_UP, CLOSE_FULL = 0.5, 0.5, 0.6, 0.8
# The plot inside the picture, in per cent of the picture: a narrow margin for the alkalinity ticks at the left and
# for the DIC ticks under it; everything else is plot.
PLOT_LEFT, PLOT_TOP, PLOT_WIDTH, PLOT_HEIGHT = 3.6, 0.8, 95.9, 94.4


@dataclass(frozen=True)
class Window:
    """The part of a figure a picture shows: from and to in DIC (mmol/L) and in alkalinity (meq/L), how much larger
    than the core's box it draws (`zoom`), whether it IS the core's box (`full`), and where the CO₂ and the NH₃ border
    cross the water's own alkalinity (DIC; None: that border does not cross it)."""
    dic: tuple
    alkalinity: tuple
    zoom: float
    full: bool
    co2: float | None = None
    nh3: float | None = None

    @property
    def ends(self):
        return (*self.dic, *self.alkalinity)


def crossing(flat, alkalinity):
    """Where a border (a flat polyline in DIC, alkalinity) crosses an alkalinity: its DIC there, or None."""
    line = _pairs(flat)
    for (x1, y1), (x2, y2) in zip(line, line[1:]):
        if (y1 - alkalinity) * (y2 - alkalinity) <= 0 and y1 != y2:
            return x1 + (alkalinity - y1) / (y2 - y1) * (x2 - x1)
    return None


def _border_at(figure, key, alkalinity):
    found = (crossing(flat, alkalinity) for name, _label, flat in figure['boundaries'] if name == key)
    return next((dic for dic in found if dic is not None), None)


def full_window(figure):
    """The core's own box, from the origin."""
    return Window((0.0, float(figure['box'][0])), (0.0, float(figure['box'][1])), 1.0, True)


def close_window(figure, band=(None, None), target_active=False):
    """The window of the CLOSE view of a figure (`figure`'s document). `band`: the alkalinity band's two ends in meq/L
    (None: the farm has not set that end); `target_active`: there is a dosing proposal, so the target must be seen.

    ACROSS (DIC), at the water's own alkalinity: the water, the target when it is active, and the place where each
    limit's border crosses that alkalinity (CO₂ on one side, NH₃ on the other). What they span is the MIDDLE HALF of
    the window: a quarter is added on each side, so each region beyond a limit keeps a quarter of the picture and one
    sees which side is which and how far it is.
    - One border missing (no limit row, no TAN): that side gets the same distance as the side there is. No border at
      all: the smallest window, around the water.
    - UP (alkalinity): the window has the box's own proportion (shapes keep the look they have at full scale) and is
      centred on the water (and the active target); when the water is outside the alkalinity band the band's nearer
      end is taken in too; what must be seen up and down takes at most CLOSE_UP of the height, and the window grows
      for it.
    - Never narrower than CLOSE_MIN. A window of CLOSE_FULL of the core's box or more IS the box (a water far beyond
      a limit): the close view is then the full scale, and says so (`full`).
    - The window is moved, never shrunk, to stay inside the core's box.
    - Old inputs change nothing: the window is around the last known position.
    While the water is between the two borders the window hangs on the BORDERS (which move with the alkalinity and
    the temperature, slowly), not on the water: a new pH moves the point inside a picture that stays put.
    Pure: the same figure gives the same window. (The mock-up's `closeWindow`, F:/dev/balik-notes/plan/pages/
    monitoring/final/chart.mjs; its 19 waters and 7 hard cases are farm/tests/close_vectors.json.)"""
    box_dic, box_alkalinity = float(figure['box'][0]), float(figure['box'][1])
    dic, alkalinity = figure['point']
    co2, nh3 = _border_at(figure, 'co2', alkalinity), _border_at(figure, 'nh3', alkalinity)
    target = figure.get('target') if target_active else None
    across = [dic] + ([target[0]] if target else []) + [border for border in (co2, nh3) if border is not None]
    left, right = min(across), max(across)
    if co2 is not None and nh3 is None:
        left = min(left, dic - abs(co2 - dic))
    if nh3 is not None and co2 is None:
        right = max(right, dic + abs(dic - nh3))
    up_down = [alkalinity] + ([target[1]] if target else [])
    low, top = band
    if low is not None and alkalinity < low:
        up_down.append(min(low, box_alkalinity))
    if top is not None and alkalinity > top:
        up_down.append(top)
    down, up = min(up_down), max(up_down)
    wide = max(CLOSE_MIN, (right - left) / CLOSE_SHARE, (up - down) / CLOSE_UP * box_dic / box_alkalinity)
    if wide >= box_dic * CLOSE_FULL:
        whole = full_window(figure)
        return Window(whole.dic, whole.alkalinity, 1.0, True, co2, nh3)
    high = wide * box_alkalinity / box_dic
    start = min(max((left + right) / 2 - wide / 2, 0.0), box_dic - wide)
    floor = min(max((down + up) / 2 - high / 2, 0.0), box_alkalinity - high)
    return Window((start, start + wide), (floor, floor + high), box_dic / wide, False, co2, nh3)


def window_of(figure, view, band=(None, None), target_active=False):
    """The window of a view of a figure: FULL the core's box, CLOSE the rule's."""
    return full_window(figure) if view == FULL else close_window(figure, band, target_active)


def card_figure(analysis, extent=()):
    """The figure a card's picture is drawn from: CARD_LAYERS of the analysis. `extent`: points the box must hold
    (`geometry`), so that the cards of one screen and one water type share ONE box in the FULL view."""
    return figure(analysis, geometry(analysis, CARD_LAYERS, extent=extent))


@dataclass(frozen=True)
class Picture:
    """A card's picture of a figure in a window, as the template prints it. In the plot (the nested SVG, 0 to 1000
    each way): `regions` (key, points), `isolines` (half, x1, y1, x2, y2: a line of equal pH every quarter, those
    every half stronger), `bounds` (key, points), `leads` (the water's two lines to the axes), `dose` (the line from
    the water to the active target). In per cent of the picture: `ph_names` (pH, decimals, x, y), `names` (where each
    region says what it is: 'co2', 'nh3', 'safe' -> (x, y)), `y_ticks` (alkalinity in mg/L as CaCO₃, x, y), `x_ticks`
    (DIC, decimals, x, y), `water`, `target`, `old_at` (where "last known position" is said), `corner` and `x_axis`
    (where the two axes are named). `locator`: the window in the core's box, 0 to 100 each way (None: the window is
    the box). Numbers are numbers here: whoever prints them writes them in the reader's language."""
    view: str
    window: Window
    plot: tuple
    regions: tuple
    isolines: tuple
    bounds: tuple
    leads: tuple
    dose: tuple | None
    ph_names: tuple
    names: dict
    y_ticks: tuple
    x_ticks: tuple
    water: tuple
    target: tuple | None
    old_at: tuple
    corner: tuple
    x_axis: tuple
    locator: tuple | None


def _one(value):
    """A coordinate at one decimal, with a dot, no trailing zero: 37.2, 1000, 0."""
    text = f'{value:.1f}'
    text = text[:-2] if text.endswith('.0') else text
    return '0' if text == '-0' else text


def _simplify(points, tolerance):
    """A polyline without the points that lie within `tolerance` of the line through the neighbours that are kept
    (Ramer-Douglas-Peucker): a border drawn 1000 units wide needs no point a pixel cannot show."""
    if len(points) < 3:
        return list(points)
    (ax, ay), (bx, by) = points[0], points[-1]
    length = math.hypot(bx - ax, by - ay) or 1.0
    far, at = 0.0, 0
    for index in range(1, len(points) - 1):
        px, py = points[index]
        distance = abs((bx - ax) * (ay - py) - (ax - px) * (by - ay)) / length
        if distance > far:
            far, at = distance, index
    if far <= tolerance:
        return [points[0], points[-1]]
    return _simplify(points[:at + 1], tolerance)[:-1] + _simplify(points[at:], tolerance)


def _inside(ring, point):
    """Whether a point lies in a polygon (even-odd)."""
    px, py = point
    odd = False
    for (ax, ay), (bx, by) in zip(ring, ring[1:] + ring[:1]):
        if (ay > py) != (by > py) and px < (bx - ax) * (py - ay) / (by - ay) + ax:
            odd = not odd
    return odd


def _clip(segment, ends):
    """The part of a segment (x1, y1, x2, y2) inside a window (Liang-Barsky), or None."""
    x1, y1, x2, y2 = segment
    xa, xb, ya, yb = ends
    dx, dy = x2 - x1, y2 - y1
    start, end = 0.0, 1.0
    for p, q in ((-dx, x1 - xa), (dx, xb - x1), (-dy, y1 - ya), (dy, yb - y1)):
        if p == 0:
            if q < 0:
                return None
            continue
        ratio = q / p
        if p < 0:
            if ratio > end:
                return None
            start = max(start, ratio)
        else:
            if ratio < start:
                return None
            end = min(end, ratio)
    return (x1 + start * dx, y1 + start * dy, x1 + end * dx, y1 + end * dy)


def _step(span, choices, about):
    return next((step for step in choices if span / step <= about), choices[-1])


# The locator (the core's box in outline, the window marked in it) draws a window never smaller than this share of the
# box each way: at x12 the true mark is a dash a wall cannot read as "here".
LOCATOR_MARK = 12
# Where a toxic region may say what it is, as fractions of the window (across, down): the first that lies in the
# region and is clear of the water's lead lines is taken.
CO2_SPOTS = ((0.82, 0.82), (0.88, 0.9), (0.88, 0.6), (0.6, 0.9), (0.45, 0.92))
NH3_SPOTS = ((0.17, 0.3), (0.15, 0.45), (0.3, 0.22), (0.15, 0.62))


def picture(figure, window, view=CLOSE, target_active=False):
    """The Picture of a figure (`card_figure`) in a window (`window_of`). `target_active`: there is a dosing proposal;
    the target and the line to it are drawn only then."""
    xa, xb, ya, yb = window.ends
    wide, high = xb - xa, yb - ya

    def x(dic):
        return (dic - xa) / wide * 1000

    def y(alkalinity):
        return (1 - (alkalinity - ya) / high) * 1000

    def px(dic):
        return PLOT_LEFT + (dic - xa) / wide * PLOT_WIDTH

    def py(alkalinity):
        return PLOT_TOP + (1 - (alkalinity - ya) / high) * PLOT_HEIGHT

    def points(flat):
        return ' '.join(f'{_one(at_x)},{_one(at_y)}'
                        for at_x, at_y in _simplify([(x(dic), y(alk)) for dic, alk in _pairs(flat)], 0.8))

    rings = {key: flat for key, _name, flat in figure['regions']}
    regions = tuple((key, points(rings[key])) for key in ('nh3', 'co2', 'safe') if key in rings)
    isolines, named = [], []
    for ph, _labelled, *segment in figure['isolines']:
        if ph < 6 or ph > 9 or (ph * 4) % 1:
            continue
        cut = _clip(segment, window.ends)
        if cut is None:
            continue
        half = (ph * 2) % 1 == 0
        isolines.append((half, _one(x(cut[0])), _one(y(cut[1])), _one(x(cut[2])), _one(y(cut[3]))))
        if half or view == CLOSE:
            named.append((ph, cut[2], cut[3]))
    bounds = tuple((key, points(flat)) for key, _name, flat in figure['boundaries'] if key in ('co2', 'nh3'))
    water_dic, water_alkalinity = figure['point']
    water_x, water_y = px(water_dic), py(water_alkalinity)
    leads = ((_one(0), _one(y(water_alkalinity)), _one(x(water_dic)), _one(y(water_alkalinity))),
             (_one(x(water_dic)), _one(y(water_alkalinity)), _one(x(water_dic)), _one(1000)))
    target = figure.get('target') if target_active else None
    dose = None if target is None else (_one(x(water_dic)), _one(y(water_alkalinity)), _one(x(target[0])),
                                        _one(y(target[1])))
    # the lines of equal pH say their pH where they leave the window, never over the water, never on each other
    ph_names, last = [], None
    for ph, end_dic, end_alkalinity in named:
        at_right = end_dic >= xb - 1e-6
        at = ((PLOT_LEFT + PLOT_WIDTH - 0.6, py(end_alkalinity) - 1.1) if at_right
              else (px(end_dic) - 0.5, PLOT_TOP + 3.4))
        crowded = last is not None and math.hypot(at[0] - last[0], (at[1] - last[1]) * 1.6) < (5.5 if at_right else 9)
        over_water = abs(at[0] - water_x) < 9 and abs(at[1] - water_y) < 7
        if (at[1] < PLOT_TOP + 3 or at[1] > PLOT_TOP + PLOT_HEIGHT - 6 or at[0] < PLOT_LEFT + 30 or crowded
                or over_water):
            continue
        last = at
        ph_names.append((ph, 2 if (ph * 2) % 1 else 1, _one(at[0]), _one(at[1])))
    # the two toxic regions say what they are where they are in this window: the first of a few fixed spots that lies
    # in the region and is clear of the water's two lead lines
    water_fx, water_fy = (water_dic - xa) / wide, (yb - water_alkalinity) / high

    def clear(fx, fy):
        return (not (abs(fx - water_fx) < 0.11 and fy > water_fy)
                and not (abs(fy - water_fy) < 0.05 and fx < water_fx + 0.11))

    def place(key, spots):
        if key not in rings:
            return None
        ring = _pairs(rings[key])
        return next(((fx, fy) for fx, fy in spots
                     if clear(fx, fy) and _inside(ring, (xa + wide * fx, yb - high * fy))), None)

    names = {}
    for key, spots in (('co2', CO2_SPOTS), ('nh3', NH3_SPOTS)):
        spot = place(key, spots)
        if spot is not None:
            names[key] = (_one(PLOT_LEFT + PLOT_WIDTH * spot[0]), _one(PLOT_TOP + PLOT_HEIGHT * spot[1]))
    if 'safe' in rings:
        ring = _pairs(rings['safe'])
        alkalinities = [point[1] for point in ring]
        low, top = max(min(alkalinities), ya), min(max(alkalinities), yb)
        at = low + (top - low) * (0.2 if water_alkalinity > (low + top) / 2 else 0.82)
        row = [point[0] for point in ring if abs(point[1] - at) < max((top - low) * 0.05, 0.02)]
        if row and top > low:
            middle = (min(row) + max(row)) / 2
            if xa < middle < xb:
                names['safe'] = (_one(px(middle)), _one(py(at) + 1))
    # ticks with the window's real numbers: alkalinity in mg/L as CaCO₃ at the left, DIC under the plot
    per_meq = chemistry.MG_CACO3_PER_MEQ
    mg_step = _step(high * per_meq, (5, 10, 20, 25, 50, 100), 6)
    dic_step = _step(wide, (0.05, 0.1, 0.2, 0.5, 1, 2), 7)
    y_ticks = []
    mg = math.ceil(ya * per_meq / mg_step) * mg_step
    while mg <= yb * per_meq:
        alkalinity = mg / per_meq
        if ya + high * 0.03 < alkalinity < yb - high * 0.03:
            y_ticks.append((mg, _one(PLOT_LEFT - 0.6), _one(py(alkalinity) + 1.1)))
        mg += mg_step
    x_ticks = []
    decimals = 2 if dic_step < 0.1 else 1 if dic_step < 1 else 0
    count = math.ceil(xa / dic_step - 1e-9)
    while count * dic_step <= xb + 1e-9:
        dic = count * dic_step
        if xa + wide * 0.03 < dic < xb - wide * 0.02:
            x_ticks.append((round(dic, 2), decimals, _one(px(dic)), _one(PLOT_TOP + PLOT_HEIGHT + 3.7)))
        count += 1
    locator = None
    if not window.full:
        box_dic, box_alkalinity = float(figure['box'][0]), float(figure['box'][1])
        locator = (_one(xa / box_dic * 100), _one((1 - yb / box_alkalinity) * 100),
                   _one(max(wide / box_dic * 100, LOCATOR_MARK)), _one(max(high / box_alkalinity * 100, LOCATOR_MARK)))
    return Picture(
        view, window, (_one(PLOT_LEFT), _one(PLOT_TOP), _one(PLOT_WIDTH), _one(PLOT_HEIGHT)), regions,
        tuple(isolines), bounds, leads, dose, tuple(ph_names), names, tuple(y_ticks), tuple(x_ticks),
        (_one(water_x), _one(water_y)), None if target is None else (_one(px(target[0])), _one(py(target[1]))),
        (_one(water_x + 1.4), _one(water_y - 2.4)), (_one(PLOT_LEFT + 0.8), _one(PLOT_TOP + 3.4)),
        (_one(PLOT_LEFT + PLOT_WIDTH - 0.6), _one(PLOT_TOP + PLOT_HEIGHT - 1.6)), locator)
